from __future__ import annotations

import json
import re

AWG_PROFILE_FIELD_ORDER = [
    "Jc",
    "Jmin",
    "Jmax",
    "S1",
    "S2",
    "S3",
    "S4",
    "H1",
    "H2",
    "H3",
    "H4",
    "I1",
    "I2",
    "I3",
    "I4",
    "I5",
]

AWG_PROFILE_PRESETS = {
    "compatible": {
        "Jc": "5",
        "Jmin": "10",
        "Jmax": "50",
        "S1": "120",
        "S2": "121",
        "S3": "0",
        "S4": "0",
        "H1": "1683627857",
        "H2": "982475688",
        "H3": "1642193332",
        "H4": "232974392",
        "I1": "0",
        "I2": "0",
        "I3": "0",
        "I4": "0",
        "I5": "0",
    },
    "balanced": {
        "Jc": "6",
        "Jmin": "12",
        "Jmax": "55",
        "S1": "120",
        "S2": "121",
        "S3": "34",
        "S4": "87",
        "H1": "1683627857",
        "H2": "982475688",
        "H3": "1642193332",
        "H4": "232974392",
        "I1": "23",
        "I2": "64",
        "I3": "178",
        "I4": "240",
        "I5": "17",
    },
    "aggressive": {
        "Jc": "7",
        "Jmin": "18",
        "Jmax": "90",
        "S1": "120",
        "S2": "121",
        "S3": "77",
        "S4": "154",
        "H1": "1683627857",
        "H2": "982475688",
        "H3": "1642193332",
        "H4": "232974392",
        "I1": "31",
        "I2": "86",
        "I3": "203",
        "I4": "251",
        "I5": "43",
    },
}

DEFAULT_AWG_PROFILE_NAME = "balanced"
DEFAULT_AWG_PROFILE = AWG_PROFILE_PRESETS[DEFAULT_AWG_PROFILE_NAME]


class AWGProfileService:
    def profile_names(self) -> list[str]:
        return list(AWG_PROFILE_PRESETS.keys())

    def is_valid_profile_name(self, profile_name: str | None) -> bool:
        return bool(profile_name and profile_name in AWG_PROFILE_PRESETS)

    def default_profile_name(self) -> str:
        return DEFAULT_AWG_PROFILE_NAME

    def default_profile(self) -> dict[str, str]:
        return dict(DEFAULT_AWG_PROFILE)

    def named_profile(self, profile_name: str | None) -> dict[str, str]:
        if profile_name and profile_name in AWG_PROFILE_PRESETS:
            return dict(AWG_PROFILE_PRESETS[profile_name])
        return self.default_profile()

    def normalize(self, fields: dict[str, str] | None) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key in AWG_PROFILE_FIELD_ORDER:
            value = (fields or {}).get(key)
            if value is None:
                continue
            stripped = str(value).strip()
            if stripped:
                normalized[key] = stripped
        return normalized

    def current_profile_name(self, subject: object | None = None) -> str:
        metadata = self._load_metadata(subject)
        profile_name = metadata.get("awg_profile_name")
        if isinstance(profile_name, str) and profile_name in AWG_PROFILE_PRESETS:
            return profile_name
        return self.default_profile_name()

    def for_subject(self, subject: object | None = None) -> dict[str, str]:
        metadata = self._load_metadata(subject)
        raw_fields = metadata.get("awg_profile_fields")
        if isinstance(raw_fields, dict):
            normalized = self.normalize({str(key): str(value) for key, value in raw_fields.items()})
            if normalized:
                return normalized
        return self.named_profile(self.current_profile_name(subject))

    def for_generated_server(self, server: object | None = None) -> dict[str, str]:
        return self.for_subject(server)

    def set_profile_metadata(self, subject: object, profile_name: str) -> None:
        metadata = self._load_metadata(subject)
        metadata["awg_profile_name"] = profile_name
        metadata["awg_profile_fields"] = self.named_profile(profile_name)
        setattr(subject, "metadata_json", json.dumps(metadata, ensure_ascii=False))

    def copy_profile_metadata(self, source: object | None, target: object) -> None:
        metadata = self._load_metadata(target)
        metadata["awg_profile_name"] = self.current_profile_name(source)
        metadata["awg_profile_fields"] = self.for_subject(source)
        setattr(target, "metadata_json", json.dumps(metadata, ensure_ascii=False))

    def apply_profile_to_config(self, config_text: str, fields: dict[str, str]) -> str:
        normalized_fields = self.normalize(fields)
        lines = config_text.splitlines()
        result: list[str] = []
        in_interface = False
        inserted = False
        pending: list[str] = []

        def flush_pending() -> None:
            nonlocal inserted
            if pending:
                result.extend(pending)
                pending.clear()
            if in_interface and not inserted:
                for key in AWG_PROFILE_FIELD_ORDER:
                    value = normalized_fields.get(key)
                    if value:
                        result.append(f"{key} = {value}")
                inserted = True

        for line in lines:
            stripped = line.strip()
            if stripped == "[Interface]":
                if in_interface:
                    flush_pending()
                in_interface = True
                inserted = False
                result.append(line)
                continue
            if stripped == "[Peer]":
                if in_interface:
                    flush_pending()
                    in_interface = False
                result.append(line)
                continue
            if in_interface:
                if not stripped:
                    flush_pending()
                    result.append(line)
                    continue
                if stripped.startswith("#"):
                    pending.append(line)
                    continue
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in AWG_PROFILE_FIELD_ORDER:
                        continue
                pending.append(line)
                continue
            result.append(line)

        if in_interface:
            flush_pending()

        rendered = "\n".join(result).strip()
        return rendered + "\n" if rendered else ""

    def _load_metadata(self, subject: object | None) -> dict[str, object]:
        metadata_json = getattr(subject, "metadata_json", None) if subject is not None else None
        if not metadata_json:
            return {}
        try:
            payload = json.loads(metadata_json)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
