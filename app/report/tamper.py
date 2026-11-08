"""Tamper evidence: the SHA-256 of the PDF bytes, and an RFC 3161 timestamp token for that hash.

Only the 32-byte hash is sent to the timestamp authority (FreeTSA by default), never the
report. Be precise about what this proves (docs/original-plan.md): the hash shows the file hasn't
changed, the token shows the hash existed at a moment in time. Neither shows the findings are
correct.

Verification pins FreeTSA's signing certificate (app/report/data/freetsa_tsa.crt), because
anyone can sign a token with a certificate of their own. rfc3161ng builds the request and
parses the token, but its own signature check only handles RSA keys, and FreeTSA's current
certificate (2026) uses an elliptic-curve key, so check_token() verifies the signature
instead. The command-line equivalent is
`openssl ts -verify -data report.pdf -in report.tsr -CAfile freetsa_cacert.pem -untrusted
freetsa_tsa.crt`.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

log = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent / "data"
FREETSA_URL = "https://freetsa.org/tsr"
FREETSA_CERT = DATA / "freetsa_tsa.crt"
TSA_TIMEOUT_SECONDS = 10

OFFLINE_MESSAGE = (
    "Couldn't get a trusted timestamp. Email the report to yourself now to keep a dated copy."
)
SKIPPED_MESSAGE = (
    "No trusted timestamp, because you chose not to go online. Email the report to yourself "
    "now to keep a dated copy."
)


# Why there's no timestamp, in plain words, by TimestampUnavailable's code.
NO_NETWORK_MESSAGE = (
    "Couldn't get a trusted timestamp: this laptop isn't connected to a network. Connect, then "
    "try again, or email the report to yourself now to keep a dated copy."
)
TIMEOUT_MESSAGE = (
    f"Couldn't get a trusted timestamp: the timestamp service didn't answer within "
    f"{TSA_TIMEOUT_SECONDS} seconds. Try again, or email the report to yourself now to keep a "
    "dated copy."
)
UNAVAILABLE_MESSAGES = {"no_network": NO_NETWORK_MESSAGE, "timeout": TIMEOUT_MESSAGE}


class TimestampUnavailable(Exception):
    """No token. args[0] is a short code: no_network, timeout, or the error's type name."""


def has_network() -> bool:
    """A quick local check (no packets sent): is there a default route at all?"""
    from app.discovery.netinfo import NoNetworkError, default_route

    try:
        default_route()
    except NoNetworkError:
        return False
    except Exception:
        log.debug("couldn't read the network; trying the timestamp anyway", exc_info=True)
    return True


class TokenMismatch(Exception):
    """The token is for a different hash: the file changed, or the files don't belong together."""


class TokenInvalid(Exception):
    """The token can't be parsed, or its signature doesn't check out."""


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def pinned_certificate(url: str) -> bytes | None:
    """FreeTSA's certificate when the URL is FreeTSA's; None for any other authority."""
    return FREETSA_CERT.read_bytes() if url.rstrip("/") == FREETSA_URL else None


def request_token(
    digest: bytes,
    url: str,
    *,
    timestamper_factory: Callable[..., Any] | None = None,
    timeout: float = TSA_TIMEOUT_SECONDS,
    network: Callable[[], bool] | None = None,
) -> bytes:
    """The DER TimeStampResp for `digest`, checked against FreeTSA's certificate when pinned.

    Ends within `timeout` seconds whatever happens: the HTTP library's own timeout doesn't
    cover looking up the server's name, which Windows can keep retrying for a minute or more
    while the network is changing. With no network at all it fails at once."""
    connected = network or has_network
    if timestamper_factory is None and not connected():  # a fake timestamper needs no network
        log.info("Timestamp authority unavailable: no network")
        raise TimestampUnavailable("no_network")
    future: Future[bytes] = Future()

    def run() -> None:
        try:
            future.set_result(_request(digest, url, timestamper_factory, timeout))
        except BaseException as e:  # handed back to the caller below
            future.set_exception(e)

    threading.Thread(target=run, name="timestamp", daemon=True).start()
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        log.info("Timestamp authority unavailable: no answer within %s s", timeout)
        raise TimestampUnavailable("timeout") from None


def _request(
    digest: bytes, url: str, timestamper_factory: Callable[..., Any] | None, timeout: float
) -> bytes:
    import rfc3161ng
    from pyasn1.codec.der import encoder

    factory = timestamper_factory or rfc3161ng.RemoteTimestamper
    # certificate=None: rfc3161ng's own check can't handle EC keys; the reply is checked below.
    timestamper = factory(
        url, certificate=None, hashname="sha256", include_tsa_certificate=True, timeout=timeout
    )
    nonce = secrets.randbits(63)
    try:
        tsr = timestamper(digest=digest, nonce=nonce, return_tsr=True)
        token = tsr.time_stamp_token
        if int(token.tst_info["nonce"]) != nonce:
            raise TokenInvalid("nonce")
        check_token(token, digest, pinned_certificate(url))
        return bytes(encoder.encode(tsr))
    except Exception as e:  # network, HTTP, a refused request or an unverifiable reply
        log.info("Timestamp authority unavailable: %s", type(e).__name__)
        raise TimestampUnavailable(type(e).__name__) from e


def check_token(token: Any, digest: bytes, certificate: bytes | None) -> None:
    """Check a TimeStampToken is genuine, then that it is for `digest`.

    `certificate`: the pinned signing certificate (PEM or DER), or None to use the one inside
    the token. Uses the cryptography library's signature verification (RSA PKCS#1 v1.5 or
    ECDSA) and hashlib; pyasn1 only parses the ASN.1. Checks, in this order:
      1. the signed attributes are present and their messageDigest equals the hash of the
         TSTInfo bytes, so the TSTInfo can't be changed without breaking the signature;
      2. the signature over the DER-encoded signed attributes verifies against the certificate;
      3. the certificate's extended key usage includes timeStamping (RFC 3161, 2.3);
      4. only then, the TSTInfo's messageImprint is SHA-256 of the file.
    Raises TokenInvalid for 1-3 (not a genuine token) and TokenMismatch for 4 (a genuine token
    for a different file).
    """
    import rfc3161ng
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID
    from pyasn1.codec.der import decoder, encoder
    from pyasn1.type import univ
    from rfc3161ng.api import get_hash_from_oid, id_attribute_messageDigest, load_certificate

    try:
        signed_data = token.content
        if signed_data["contentInfo"]["contentType"] != rfc3161ng.id_ct_TSTInfo:
            raise TokenInvalid("content type")
        if not len(signed_data["signerInfos"]):
            raise TokenInvalid("no signature")
        signer = signed_data["signerInfos"][0]
        hash_name = get_hash_from_oid(signer["digestAlgorithm"]["algorithm"])
        inner = bytes(signed_data["contentInfo"]["content"])
        tst_info_bytes = bytes(decoder.decode(inner, asn1Spec=univ.OctetString())[0])

        # 1. messageDigest (a signed attribute) must be the hash of the TSTInfo.
        attributes = signer["authenticatedAttributes"]
        if not len(attributes):
            raise TokenInvalid("no signed attributes")
        signed_digest = None
        for attribute in attributes:
            if attribute[0] == id_attribute_messageDigest:
                value = bytes(attribute[1][0])
                signed_digest = bytes(decoder.decode(value, asn1Spec=univ.OctetString())[0])
                break
        if signed_digest is None:
            raise TokenInvalid("no messageDigest attribute")
        if signed_digest != hashlib.new(hash_name, tst_info_bytes).digest():
            raise TokenInvalid("TSTInfo doesn't match its messageDigest")

        # 2. The signature covers the signed attributes, re-encoded as a DER SET OF.
        attribute_set = univ.SetOf()
        for i, attribute in enumerate(attributes):
            attribute_set.setComponentByPosition(i, attribute)
        signed_bytes = bytes(encoder.encode(attribute_set))
        cert = load_certificate(signed_data, certificate if certificate is not None else b"")
        key = cert.public_key()
        algorithm = getattr(hashes, hash_name.upper())()
        signature = bytes(signer["encryptedDigest"])
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, signed_bytes, padding.PKCS1v15(), algorithm)
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, signed_bytes, ec.ECDSA(algorithm))
        else:
            raise TokenInvalid("unsupported key type")

        # 3. The certificate must be issued for time stamping.
        try:
            usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        except x509.ExtensionNotFound:
            raise TokenInvalid("certificate has no extended key usage") from None
        if ExtendedKeyUsageOID.TIME_STAMPING not in usage:
            raise TokenInvalid("certificate isn't for time stamping")

        # 4. Only a genuine token gets compared with the file.
        imprint = token.tst_info.message_imprint
        if imprint.hash_algorithm[0] != rfc3161ng.id_sha256:
            raise TokenMismatch("hash algorithm")
        if bytes(imprint.hashed_message) != digest:
            raise TokenMismatch("imprint")
    except (TokenMismatch, TokenInvalid):
        raise
    except InvalidSignature as e:
        raise TokenInvalid("signature") from e
    except Exception as e:  # malformed ASN.1, missing fields, unreadable certificate
        raise TokenInvalid(type(e).__name__) from e


def token_time(tsr: bytes) -> datetime:
    import rfc3161ng

    return rfc3161ng.get_timestamp(_token(tsr), naive=False).astimezone(UTC)


def _token(data: bytes) -> Any:
    """The TimeStampToken in a .tsr file, which may hold a whole response or just the token."""
    import rfc3161ng
    from pyasn1.codec.der import decoder

    try:
        return rfc3161ng.decode_timestamp_response(data).time_stamp_token
    except Exception:
        token, rest = decoder.decode(data, asn1Spec=rfc3161ng.TimeStampToken())
        if rest:
            raise ValueError("extra data after the token") from None
        return token


# --- saving --------------------------------------------------------------------------------


class ReportFiles(BaseModel):
    pdf: Path
    sha256: str
    sha256_file: Path
    tsr: Path | None = None
    timestamped_at: datetime | None = None
    timestamp_message: str | None = None  # shown to the user when there is no token


def save(
    pdf: bytes,
    out_dir: Path,
    stem: str,
    *,
    tsa_url: str = FREETSA_URL,
    online: bool = True,
    request: Callable[[bytes, str], bytes] = request_token,
) -> ReportFiles:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{stem}.pdf"
    pdf_path.write_bytes(pdf)
    digest = sha256(pdf)
    hash_path = out_dir / f"{stem}.sha256"
    hash_path.write_text(f"{digest.hex()}  {pdf_path.name}\n", encoding="ascii")
    files = ReportFiles(pdf=pdf_path, sha256=digest.hex(), sha256_file=hash_path)
    if not online:
        files.timestamp_message = SKIPPED_MESSAGE
        return files
    try:
        tsr = request(digest, tsa_url)
    except TimestampUnavailable as e:
        code = str(e.args[0]) if e.args else ""
        files.timestamp_message = UNAVAILABLE_MESSAGES.get(code, OFFLINE_MESSAGE)
        return files
    tsr_path = out_dir / f"{stem}.tsr"
    tsr_path.write_bytes(tsr)
    files.tsr = tsr_path
    files.timestamped_at = token_time(tsr)
    return files


# --- verifying -----------------------------------------------------------------------------

HashCheck = Literal["match", "mismatch", "missing"]
TokenCheck = Literal["valid", "mismatch", "invalid", "missing"]
# verified: the token is valid, from the pinned authority, and the PDF matches it.
# mismatch: the token is valid, but the PDF's hash differs ("Files don't match").
# couldnt_verify: not a PDF, an unreadable token, or an untrusted certificate (see reason).
# not_timestamped: no token, so there's nothing to verify against. Never "altered".
VerifyOutcome = Literal["verified", "mismatch", "couldnt_verify", "not_timestamped"]
NOT_TIMESTAMPED = "This report wasn't timestamped, so it can't be timestamp-verified."
NOT_PROOF = (
    "Verifying shows the report hasn't changed since it was timestamped. It doesn't prove the "
    "findings are correct."
)


class VerifyResult(BaseModel):
    sha256: str
    hash_file: HashCheck
    token: TokenCheck
    timestamped_at: datetime | None = None
    pinned_authority: bool | None = None  # True: signed by FreeTSA's pinned certificate
    outcome: VerifyOutcome
    reason: str | None = None  # couldnt_verify: the specific reason
    ok: bool
    message: str


def read_hash_file(text: str) -> str | None:
    """The hex digest from a `<hex>  <name>` line (sha256sum format), or None."""
    first = text.strip().split()[:1]
    if first and len(first[0]) == 64 and all(c in "0123456789abcdefABCDEF" for c in first[0]):
        return first[0].lower()
    return None


def _check_token(
    tsr: bytes, digest: bytes, cert: bytes
) -> tuple[TokenCheck, datetime | None, bool | None]:
    import rfc3161ng

    try:
        token = _token(tsr)
        when = rfc3161ng.get_timestamp(token, naive=False).astimezone(UTC)
    except Exception:
        return "invalid", None, None
    try:
        check_token(token, digest, cert)
        return "valid", when, True
    except TokenMismatch:
        return "mismatch", when, None
    except TokenInvalid:
        pass
    # Not signed by the pinned certificate: check it against the certificate it carries.
    try:
        check_token(token, digest, None)
        return "valid", when, False
    except (TokenMismatch, TokenInvalid):
        return "invalid", when, None


def verify(
    pdf: bytes,
    tsr: bytes | None = None,
    expected_sha256: str | None = None,
    *,
    certificate: bytes | None = None,
) -> VerifyResult:
    digest = sha256(pdf)
    hex_digest = digest.hex()
    if not pdf.startswith(b"%PDF-"):
        not_pdf = "This file isn't a PDF, so it can't be a RoomCheck report."
        unchecked: TokenCheck = "missing"
        return VerifyResult(
            sha256=hex_digest,
            hash_file="missing",
            token=unchecked,
            outcome="couldnt_verify",
            reason=not_pdf,
            ok=False,
            message=not_pdf,
        )
    if expected_sha256 is None:
        hash_file: HashCheck = "missing"
    else:
        hash_file = "match" if expected_sha256.lower() == hex_digest else "mismatch"

    stamp_check: TokenCheck = "missing"
    when: datetime | None = None
    pinned: bool | None = None
    if tsr is not None:
        cert = certificate or FREETSA_CERT.read_bytes()
        stamp_check, when, pinned = _check_token(tsr, digest, cert)

    stamp_text = f"{when:%d %b %Y, %H:%M:%S} UTC" if when else ""
    if stamp_check == "valid" and pinned:
        message = (
            f"This PDF matches its timestamp: it existed, unchanged, on {stamp_text}, as signed by "
            "FreeTSA. This shows when the report existed, not that its findings are correct."
        )
    elif stamp_check == "valid":
        message = (
            f"This PDF matches a timestamp from {stamp_text}, but the token wasn't signed by "
            "FreeTSA. "
            "It was only checked against the certificate inside it, so check that authority "
            "yourself (for example with openssl ts -verify)."
        )
    elif stamp_check == "mismatch":
        message = (
            "This PDF doesn't match its timestamp. It was changed after it was timestamped, or "
            "the two files don't belong together."
        )
    elif stamp_check == "invalid":
        message = "The timestamp file couldn't be verified. It may be damaged, or not a timestamp."
    elif hash_file == "match":
        message = (
            "No timestamp file was found. The PDF matches its saved SHA-256 hash, so it hasn't "
            "changed since the hash was saved, but that alone doesn't show when it was made."
        )
    elif hash_file == "mismatch":
        message = (
            "No timestamp file was found, and the PDF doesn't match its saved hash: "
            "it has been changed."
        )
    else:
        message = (
            "No timestamp or hash file was found, so there is nothing to check this PDF against."
        )
    if stamp_check == "valid" and hash_file == "mismatch":
        message += (
            " Its .sha256 file doesn't match, so that file has been changed or belongs to "
            "another report."
        )

    outcome: VerifyOutcome
    reason: str | None = None
    if stamp_check == "valid" and pinned:
        outcome = "verified"
    elif stamp_check == "mismatch":
        outcome = "mismatch"
    elif stamp_check == "missing":
        # No token: explained, never called altered, whatever the .sha256 file says.
        outcome = "not_timestamped"
        message = NOT_TIMESTAMPED
        if hash_file == "match":
            message += " It does match its .sha256 file, so it hasn't changed since that was saved."
        elif hash_file == "mismatch":
            message += " Its .sha256 file doesn't match it, so the two may not belong together."
    else:
        outcome = "couldnt_verify"
        reason = (
            "The timestamp wasn't signed by the timestamp service RoomCheck uses, so it can't be "
            "trusted here."
            if stamp_check == "valid"
            else "The timestamp file is damaged or isn't a timestamp."
        )
    ok = outcome == "verified" and hash_file != "mismatch"
    return VerifyResult(
        sha256=hex_digest,
        hash_file=hash_file,
        token=stamp_check,
        timestamped_at=when,
        pinned_authority=pinned,
        outcome=outcome,
        reason=reason,
        ok=ok,
        message=message,
    )
