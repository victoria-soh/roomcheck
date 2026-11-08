"""The handover state for this run of RoomCheck: the matching salt, recognition answers,
names, notes, task states and the move-in baseline, backed by the encrypted store.

Every change to the handover data is saved straight away, encrypted for this Windows account,
whether or not a move-in scan exists; the salt is saved with it, so later checks match the
same devices. "Delete move-in scan" removes only the move-in scan.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.baseline.compare import compare, snapshot
from app.baseline.models import Baseline, BaselineFacts, Comparison, MatchDecision
from app.baseline.store import BaselineStore, BaselineUnreadable
from app.discovery.messages import message_for
from app.discovery.models import DiscoveryResult
from app.handover import tasks as task_rules
from app.handover.models import (
    MAX_RECHECKS,
    Answer,
    HandoverState,
    PhysicalCheck,
    PhysicalItem,
    PhysicalItemId,
    Recheck,
    TaskState,
    TaskStatus,
)
from app.rules.models import Location

log = logging.getLogger(__name__)

SALT_BYTES = 32
_answers = TypeAdapter(dict[str, Answer])
_confirmed = TypeAdapter(dict[str, bool])
_locations = TypeAdapter(dict[str, Location])
_names = TypeAdapter(dict[str, str])
_notes = TypeAdapter(dict[str, str])
_states = TypeAdapter(dict[str, TaskState])
_matches = TypeAdapter(dict[str, MatchDecision])


class BaselineInfo(BaseModel):
    state: Literal["none", "saved", "unreadable"]
    saved_at: datetime | None = None
    devices: int = 0
    nearby: int = 0
    message: str | None = None  # plain words, e.g. the DPAPI failure message


class HandoverSession:
    def __init__(self, store: BaselineStore) -> None:
        self.store = store
        self._lock = threading.Lock()
        self.salt = secrets.token_bytes(SALT_BYTES)
        self.answers: dict[str, Answer] = {}
        self.confirmed: dict[str, bool] = {}
        self.locations: dict[str, Location] = {}  # a camera's "Where is it?"
        self.names: dict[str, str] = {}
        self.notes: dict[str, str] = {}
        self.states: dict[str, TaskState] = {}
        self.matches: dict[str, MatchDecision] = {}  # "possibly the same device" answers
        self.room_label: str | None = None  # the last report's room label, offered next time
        self.physical = PhysicalCheck()  # the guided physical check
        self.baseline: Baseline | None = None
        self.unreadable = False
        self.storage_error: str | None = None  # why the last change wasn't saved, if it wasn't
        self._load()

    # --- the store ---------------------------------------------------------------------------

    def _load(self) -> None:
        try:
            salt = self.store.read("salt")
            saved = self.store.read("baseline")
            if saved is not None and not isinstance(salt, str):
                raise ValueError("no salt")
            if isinstance(salt, str):
                self.salt = bytes.fromhex(salt)
            if saved is not None:
                self.baseline = Baseline.model_validate(saved)
            self.answers = _answers.validate_python(self.store.read("answers") or {})
            self.confirmed = _confirmed.validate_python(self.store.read("confirmed") or {})
            self.locations = _locations.validate_python(self.store.read("locations") or {})
            self.names = _names.validate_python(self.store.read("names") or {})
            self.notes = _notes.validate_python(self.store.read("notes") or {})
            self.states = _states.validate_python(self.store.read("tasks") or {})
            self.matches = _matches.validate_python(self.store.read("matches") or {})
            physical = self.store.read("physical")
            if physical is not None:
                self.physical = PhysicalCheck.model_validate(physical)
            label = self.store.read("room_label")
            self.room_label = label if isinstance(label, str) and label else None
        except (BaselineUnreadable, ValidationError, ValueError, TypeError):
            # Another Windows account or install, or a damaged file. Keep going with a fresh
            # salt; the screens say so and offer to start a new baseline.
            log.warning("move-in baseline couldn't be read")
            self.baseline = None
            self.unreadable = True

    @property
    def saved(self) -> bool:
        return self.baseline is not None

    def _persist(self, values: dict[str, Any]) -> None:
        """Save a change straight away, with the salt. Never raises: a failure is kept in
        storage_error and shown as "Not saved" with the reason."""
        if self.unreadable:
            self.storage_error = message_for("handover_unreadable")
            return
        try:
            self.store.write({"salt": self.salt.hex(), **values})
        except (OSError, sqlite3.Error):
            log.warning("handover data couldn't be saved")
            self.storage_error = message_for("handover_not_saved")
            return
        self.storage_error = None

    def _states_json(self) -> dict[str, Any]:
        return {k: v.model_dump(mode="json") for k, v in self.states.items()}

    def info(self) -> BaselineInfo:
        if self.unreadable:
            return BaselineInfo(state="unreadable", message=message_for("baseline_unreadable"))
        if self.baseline is None:
            return BaselineInfo(state="none")
        return BaselineInfo(
            state="saved",
            saved_at=self.baseline.saved_at,
            devices=len(self.baseline.devices) + self.baseline.unkeyed_devices,
            nearby=len(self.baseline.nearby),
        )

    def save_baseline(self, result: DiscoveryResult, now: datetime | None = None) -> BaselineInfo:
        """Save this check as the move-in scan, with the answers and task states so far.
        Replaces any earlier (or unreadable) baseline."""
        with self._lock:
            baseline = snapshot(result, self.salt, now or datetime.now(UTC))
            if self.unreadable:
                self.store.delete()  # an unreadable old file is replaced, not appended to
            self.baseline = baseline
            self.matches = {}  # answers about the old move-in scan's devices don't carry over
            self.unreadable = False
            self.storage_error = None
            self.store.write(
                {
                    "salt": self.salt.hex(),
                    "baseline": baseline.model_dump(mode="json"),
                    "answers": dict(self.answers),
                    "confirmed": dict(self.confirmed),
                    "names": dict(self.names),
                    "notes": dict(self.notes),
                    "tasks": self._states_json(),
                    "matches": {},
                }
            )
            return self.info()

    def delete_all(self) -> None:
        """Delete every saved value (the move-in scan, tasks, statuses, notes, answers, names,
        notes and the salt) from disk and from this run, and start again with a new salt."""
        with self._lock:
            self.store.delete()
            self.salt = secrets.token_bytes(SALT_BYTES)
            self.answers = {}
            self.confirmed = {}
            self.locations = {}
            self.names = {}
            self.notes = {}
            self.states = {}
            self.matches = {}
            self.room_label = None
            self.physical = PhysicalCheck()
            self.baseline = None
            self.unreadable = False
            self.storage_error = None

    def delete_baseline(self) -> BaselineInfo:
        """Delete the move-in scan from disk. The handover data stays saved."""
        with self._lock:
            if self.unreadable:
                self.store.delete()  # nothing in it can be read: start again
                self.unreadable = False
            else:
                self.store.remove("baseline")
                self.store.remove("matches")
            self.baseline = None
            self.matches = {}
            return self.info()

    # --- answers and tasks -------------------------------------------------------------------

    def facts(self) -> BaselineFacts | None:
        return BaselineFacts.of(self.baseline, self.salt) if self.baseline else None

    def set_answer(
        self, subject: str, answer: Answer | None, confirmed: bool | None = None
    ) -> None:
        """confirmed: for "Host's" only, the answer to "Has the host confirmed this?"."""
        with self._lock:
            if answer is None:
                self.answers.pop(subject, None)  # back to no answer
            else:
                self.answers[subject] = answer
            if answer == "landlord" and confirmed is not None:
                self.confirmed[subject] = confirmed
            elif answer != "landlord":
                self.confirmed.pop(subject, None)  # only a host's device can be confirmed
            self._persist({"answers": dict(self.answers), "confirmed": dict(self.confirmed)})

    def set_location(self, subject: str, location: Location | None) -> None:
        """A camera's "Where is it?"; None goes back to no answer. Saved like the answers."""
        with self._lock:
            if location is None:
                self.locations.pop(subject, None)
            else:
                self.locations[subject] = location
            self._persist({"locations": dict(self.locations)})

    def set_match(self, match: str, decision: MatchDecision | None) -> None:
        """The answer to "possibly the same device"; None goes back to no answer. Saved,
        encrypted, like the recognition answers."""
        with self._lock:
            if decision is None:
                self.matches.pop(match, None)
            else:
                self.matches[match] = decision
            self._persist({"matches": dict(self.matches)})

    def set_room_label(self, label: str) -> None:
        """The room label of the last report, saved encrypted like the other answers."""
        with self._lock:
            self.room_label = label
            self._persist({"room_label": label})

    def set_physical_item(
        self, item: PhysicalItemId, looked: bool | None, note: str | None
    ) -> None:
        """One place in the physical check: ticked or not, and its note (already cleaned)."""
        with self._lock:
            current = self.physical.items.get(item, PhysicalItem())
            if looked is not None:
                current.looked = looked
            if note is not None:
                current.note = note
            self.physical.items[item] = current
            self._persist({"physical": self.physical.model_dump(mode="json")})

    def finish_physical(self, done: bool, now: datetime | None = None) -> None:
        """Done (with the date), or back to in progress."""
        with self._lock:
            self.physical.done_at = (now or datetime.now(UTC)) if done else None
            self._persist({"physical": self.physical.model_dump(mode="json")})

    def set_name(self, subject: str, name: str) -> None:
        """A short plain-text name (already cleaned); "" removes it. Saved, encrypted, with the
        move-in scan once there is one, like the answers."""
        with self._lock:
            if name:
                self.names[subject] = name
            else:
                self.names.pop(subject, None)
            self._persist({"names": dict(self.names)})

    def set_note(self, subject: str, note: str) -> None:
        """A short plain-text note (already cleaned); "" removes it. Saved like the names."""
        with self._lock:
            if note:
                self.notes[subject] = note
            else:
                self.notes.pop(subject, None)
            self._persist({"notes": dict(self.notes)})

    def update_task(
        self,
        task_id: str,
        status: TaskStatus | None,
        notes: str | None,
        now: datetime | None = None,
        *,
        host_confirmed: bool | None = None,
        check_at: datetime | None = None,
    ) -> None:
        """check_at: when the check this task came from started, kept with its first change."""
        with self._lock:
            now = now or datetime.now(UTC)
            state = self.states.get(task_id, TaskState())
            if status is not None:
                state.status = status
            if notes is not None:
                state.notes = notes
            if host_confirmed is not None and host_confirmed != state.host_confirmed:
                state.host_confirmed = host_confirmed
                state.host_confirmed_at = now if host_confirmed else None
            if state.check_at is None:
                state.check_at = check_at
            state.changed_at = now
            self.states[task_id] = state
            self._persist({"tasks": self._states_json()})

    def save_recheck(self, task_id: str, recheck: Recheck) -> None:
        with self._lock:
            state = self.states.get(task_id, TaskState())
            state.rechecks = [*state.rechecks, recheck][-MAX_RECHECKS:]
            self.states[task_id] = state
            self._persist({"tasks": self._states_json()})

    def state_for(self, result: DiscoveryResult | None) -> HandoverState:
        if result is None:
            return HandoverState(
                answers=dict(self.answers),
                confirmed=dict(self.confirmed),
                locations=dict(self.locations),
                names=dict(self.names),
                notes=dict(self.notes),
                saved=self.saved,
                physical=self.physical.model_copy(deep=True),
                **self._storage(),
            )
        tasks = task_rules.build_tasks(result, self.answers, self.states, confirmed=self.confirmed)
        ai_message = result.explanations.landlord_message if result.explanations else None
        adjusted = {}
        for f in result.findings:
            steps = task_rules.adjusted_steps(
                f,
                self.answers.get(f.subject or ""),
                location=self.locations.get(f.subject or ""),
                stay=result.stay_type,
            )
            if steps is not None:
                adjusted[f.id] = steps
        return HandoverState(
            answers=dict(self.answers),
            confirmed=dict(self.confirmed),
            locations=dict(self.locations),
            names=dict(self.names),
            notes=dict(self.notes),
            adjusted=adjusted,
            tasks=tasks,
            message=task_rules.bundle_message(tasks, ai_message),
            saved=self.saved,
            physical=self.physical.model_copy(deep=True),
            **self._storage(),
        )

    def _storage(self) -> dict[str, Any]:
        if self.storage_error:
            return {"storage": "not_saved", "storage_reason": self.storage_error}
        return {"storage": "saved", "storage_reason": None}

    def comparison(self, result: DiscoveryResult) -> Comparison | None:
        return compare(self.baseline, result, self.salt, self.matches) if self.baseline else None
