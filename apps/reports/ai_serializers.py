import json

from rest_framework import serializers


class ReportAiMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField()


class ReportAiAssistSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    mineral_name = serializers.CharField(required=False, allow_blank=True)
    region_name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    context_text = serializers.CharField(required=False, allow_blank=True)
    instruction = serializers.CharField(required=False, allow_blank=True)
    current_executive_summary = serializers.CharField(required=False, allow_blank=True)
    current_key_findings = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )
    messages = ReportAiMessageSerializer(many=True, required=False)

    def validate_messages(self, value):
        return value or []

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

    @classmethod
    def from_request(cls, request):
        if request.content_type and "multipart" in request.content_type:
            data = request.data.copy()
            raw_messages = data.get("messages")
            if isinstance(raw_messages, str) and raw_messages.strip():
                try:
                    data["messages"] = json.loads(raw_messages)
                except json.JSONDecodeError:
                    data["messages"] = []
            raw_findings = data.get("current_key_findings")
            if isinstance(raw_findings, str) and raw_findings.strip():
                try:
                    data["current_key_findings"] = json.loads(raw_findings)
                except json.JSONDecodeError:
                    data["current_key_findings"] = []
            return cls(data=data)
        return cls(data=request.data)
