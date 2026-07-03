class AuditMiddleware:
    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method in self.WRITE_METHODS
            and request.path.startswith("/api/v1/")
            and request.user.is_authenticated
            and response.status_code < 400
        ):
            from apps.compliance.views import log_audit

            log_audit(
                request,
                action=f"{request.method} {request.path}",
                resource_type="api",
                resource_id="",
                details={"path": request.path},
            )
        return response
