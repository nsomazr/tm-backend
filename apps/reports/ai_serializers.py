import json

from rest_framework import serializers


def _normalize_string_list(raw) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [line.strip() for line in text.splitlines() if line.strip()]
        raw = parsed

    if isinstance(raw, dict):
        if raw and all(str(key).isdigit() for key in raw):
            raw = [raw[key] for key in sorted(raw, key=lambda value: int(value))]
        else:
            return []

    if not isinstance(raw, list):
        text = str(raw).strip()
        return [text] if text else []

    items: list[str] = []
    for entry in raw:
        if isinstance(entry, str):
            text = entry.strip()
            if text:
                items.append(text)
        elif isinstance(entry, (int, float, bool)):
            items.append(str(entry))
        elif isinstance(entry, dict):
            text = str(entry.get("text") or entry.get("content") or entry.get("value") or "").strip()
            if text:
                items.append(text)
    return items


def _normalize_messages(raw) -> list[dict[str, str]]:
    if raw is None:
        return []

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return []

    if not isinstance(raw, list):
        return []

    messages: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = str(entry.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


class StringListField(serializers.Field):
    def to_internal_value(self, data):
        return _normalize_string_list(data)

    def to_representation(self, value):
        return _normalize_string_list(value)


class ChatMessagesField(serializers.Field):
    def to_internal_value(self, data):
        return _normalize_messages(data)

    def to_representation(self, value):
        return _normalize_messages(value)


class ReportAiAssistSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    mineral_name = serializers.CharField(required=False, allow_blank=True)
    region_name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    context_text = serializers.CharField(required=False, allow_blank=True)
    instruction = serializers.CharField(required=False, allow_blank=True)
    current_executive_summary = serializers.CharField(required=False, allow_blank=True)
    current_key_findings = StringListField(required=False)
    messages = ChatMessagesField(required=False)
    enable_web_search = serializers.CharField(required=False, allow_blank=True, default="false")

    def validated_chat_messages(self) -> list[dict[str, str]]:
        instruction = (self.validated_data.get("instruction") or "").strip()
        messages = list(self.validated_data.get("messages") or [])
        if instruction:
            messages.append({"role": "user", "content": instruction})
        return messages

    def validated_metadata(self) -> dict:
        return {
            "title": self.validated_data.get("title") or "",
            "mineral_name": self.validated_data.get("mineral_name") or "",
            "region_name": self.validated_data.get("region_name") or "",
            "description": self.validated_data.get("description") or "",
        }

    def validated_current_draft(self) -> dict | None:
        summary = (self.validated_data.get("current_executive_summary") or "").strip()
        findings = self.validated_data.get("current_key_findings") or []
        if not summary and not findings:
            return None
        return {"executive_summary": summary, "key_findings": findings}

    def validated_enable_web_search(self) -> bool:
        raw = self.validated_data.get("enable_web_search") or "false"
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def from_request(cls, request):
        raw = request.data
        if hasattr(raw, "keys"):
            data = {key: raw.get(key) for key in raw.keys()}
        else:
            data = dict(raw)
        return cls(data=data)
