from __future__ import annotations

from app.models.server import Server

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

DEFAULT_AWG_PROFILE = {
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
}


class AWGProfileService:
    def default_profile(self) -> dict[str, str]:
        return dict(DEFAULT_AWG_PROFILE)

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

    def for_generated_server(self, server: Server | None = None) -> dict[str, str]:
        return self.default_profile()

