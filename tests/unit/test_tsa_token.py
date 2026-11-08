"""RFC 3161 token checks against forgeries built from a real FreeTSA token:
a token re-signed by a different key, an attacker's own certificate (with and without the
timeStamping extended key usage), and a tampered TSTInfo. No network."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import rfc3161ng
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyasn1.codec.der import decoder, encoder
from pyasn1.type import univ
from pyasn1_modules import rfc2459
from rfc3161ng.api import get_hash_from_oid

from app.report import tamper

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "report"
PDF = (FIXTURES / "sample.pdf").read_bytes()
TSR = (FIXTURES / "sample.tsr").read_bytes()
DIGEST = tamper.sha256(PDF)
FREETSA = tamper.FREETSA_CERT.read_bytes()


def parts():
    tsr = rfc3161ng.decode_timestamp_response(TSR)
    token = tsr.time_stamp_token
    return tsr, token, token.content, token.content["signerInfos"][0]


def signed_attribute_bytes(signer) -> bytes:
    attribute_set = univ.SetOf()
    for i, attribute in enumerate(signer["authenticatedAttributes"]):
        attribute_set.setComponentByPosition(i, attribute)
    return bytes(encoder.encode(attribute_set))


def hash_for(signer):
    return getattr(hashes, get_hash_from_oid(signer["digestAlgorithm"]["algorithm"]).upper())()


def make_cert(key, usage=ExtendedKeyUsageOID.TIME_STAMPING) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Not FreeTSA")])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2036, 1, 1, tzinfo=UTC))
    )
    if usage is not None:
        builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=True)
    return builder.sign(key, hashes.SHA256())


def forge(key=None, cert: x509.Certificate | None = None, tst=None) -> bytes:
    """The real token, optionally with a changed TSTInfo, re-signed by `key`, and with
    `cert` embedded in place of FreeTSA's certificate."""
    tsr, token, signed_data, signer = parts()
    if tst is not None:
        inner = bytes(signed_data["contentInfo"]["content"])
        old = bytes(decoder.decode(inner, asn1Spec=univ.OctetString())[0])
        new = tst(old)
        assert new != old
        content = signed_data["contentInfo"]["content"]
        signed_data["contentInfo"]["content"] = content.clone(encoder.encode(univ.OctetString(new)))
    if key is not None:
        signature = key.sign(signed_attribute_bytes(signer), ec.ECDSA(hash_for(signer)))
        signer["encryptedDigest"] = signer["encryptedDigest"].clone(signature)
    if cert is not None:
        der = cert.public_bytes(serialization.Encoding.DER)
        replacement = decoder.decode(der, asn1Spec=rfc2459.Certificate())[0]
        signed_data["certificates"][0]["certificate"] = replacement
    return bytes(encoder.encode(tsr))


def token_of(tsr_bytes: bytes):
    return rfc3161ng.decode_timestamp_response(tsr_bytes).time_stamp_token


def pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


# --- the genuine token passes all four checks ------------------------------------------------


def test_genuine_token_passes():
    tamper.check_token(token_of(TSR), DIGEST, FREETSA)  # no exception
    assert tamper.verify(PDF, TSR).ok


def test_freetsa_certificate_is_for_time_stamping():
    cert = x509.load_pem_x509_certificate(FREETSA)
    usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.TIME_STAMPING in usage


def test_unchanged_round_trip_still_verifies():
    # Re-encoding the parsed token must not change it, or the forgery tests prove nothing.
    assert forge() == TSR


# --- a token signed by a different key -------------------------------------------------------


def test_token_resigned_by_another_key_fails_against_pinned_certificate():
    other = ec.generate_private_key(ec.SECP384R1())
    forged = forge(key=other)
    with pytest.raises(tamper.TokenInvalid, match="signature"):
        tamper.check_token(token_of(forged), DIGEST, FREETSA)
    r = tamper.verify(PDF, forged)
    assert (r.token, r.ok) == ("invalid", False)


def test_attacker_certificate_inside_token_is_never_trusted_as_freetsa():
    other = ec.generate_private_key(ec.SECP384R1())
    forged = forge(key=other, cert=make_cert(other))
    r = tamper.verify(PDF, forged)
    # Valid by its own certificate only: reported, but never "OK".
    assert (r.token, r.pinned_authority, r.ok) == ("valid", False, False)
    assert "wasn't signed by FreeTSA" in r.message


# --- the certificate must have the timeStamping extended key usage ---------------------------


@pytest.mark.parametrize("usage", [None, ExtendedKeyUsageOID.SERVER_AUTH])
def test_certificate_without_time_stamping_usage_is_rejected(usage):
    other = ec.generate_private_key(ec.SECP384R1())
    cert = make_cert(other, usage=usage)
    forged = forge(key=other, cert=cert)
    with pytest.raises(tamper.TokenInvalid, match="extended key usage|time stamping"):
        tamper.check_token(token_of(forged), DIGEST, pem(cert))
    r = tamper.verify(PDF, forged)
    assert (r.token, r.ok) == ("invalid", False)


def test_same_forgery_with_time_stamping_usage_passes_when_that_cert_is_pinned():
    # Shows the EKU check is what rejected the case above, not something else.
    other = ec.generate_private_key(ec.SECP384R1())
    cert = make_cert(other)
    tamper.check_token(token_of(forge(key=other, cert=cert)), DIGEST, pem(cert))


# --- a tampered TSTInfo ----------------------------------------------------------------------


def test_tampered_tstinfo_breaks_the_message_digest():
    forged = forge(tst=lambda b: b.replace(b"2026", b"2027", 1))  # a later genTime
    with pytest.raises(tamper.TokenInvalid, match="messageDigest"):
        tamper.check_token(token_of(forged), DIGEST, FREETSA)
    assert tamper.verify(PDF, forged).token == "invalid"


def test_tstinfo_rewritten_for_another_pdf_is_invalid_not_a_mismatch():
    other_pdf = PDF + b"%forged\n"
    forged = forge(tst=lambda b: b.replace(DIGEST, tamper.sha256(other_pdf)))
    r = tamper.verify(other_pdf, forged)
    assert (r.token, r.ok) == ("invalid", False)


def test_tampered_tstinfo_with_matching_resignature_still_fails_pinned_check():
    other = ec.generate_private_key(ec.SECP384R1())
    forged = forge(key=other, tst=lambda b: b.replace(b"2026", b"2027", 1))
    with pytest.raises(tamper.TokenInvalid):
        tamper.check_token(token_of(forged), DIGEST, FREETSA)


# --- the imprint check -----------------------------------------------------------------------


def test_genuine_token_for_a_different_file_is_a_mismatch():
    with pytest.raises(tamper.TokenMismatch):
        tamper.check_token(token_of(TSR), tamper.sha256(b"another file"), FREETSA)
