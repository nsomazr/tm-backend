def _ttl_label(minutes: int) -> str:
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {unit}"


def otp_email_html(code: str, purpose: str, ttl_minutes: int) -> str:
    action = "sign in to" if purpose == "login" else "verify your email on"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Terra Meta verification code</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:480px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(15,23,42,0.08);">
          <tr>
            <td style="background:linear-gradient(135deg,#1e3a2f 0%,#2d5a47 100%);padding:28px 32px;text-align:center;">
              <p style="margin:0 0 6px;font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.75);">Terra Meta</p>
              <h1 style="margin:0;font-size:22px;font-weight:700;color:#ffffff;line-height:1.3;">Your verification code</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#475569;">
                Use this code to {action} Terra Meta. It expires in <strong>{_ttl_label(ttl_minutes)}</strong>.
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center" style="background:#f0fdf4;border:2px dashed #86efac;border-radius:12px;padding:24px 16px;">
                    <p style="margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#166534;">Verification code</p>
                    <p style="margin:0;font-size:36px;font-weight:800;letter-spacing:0.35em;color:#14532d;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;">{code}</p>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:#94a3b8;text-align:center;">
                If you did not request this code, you can safely ignore this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 28px;border-top:1px solid #f1f5f9;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.5;">
                Terra Meta by <a href="https://5ggeology.com" style="color:#2d5a47;text-decoration:none;font-weight:600;">5G Geology</a><br />
                Mineral intelligence for Tanzania
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def otp_email_text(code: str, purpose: str, ttl_minutes: int) -> str:
    action = "sign in to" if purpose == "login" else "verify your email on"
    return (
        f"Terra Meta: Your verification code\n\n"
        f"Use this code to {action} Terra Meta:\n\n"
        f"  {code}\n\n"
        f"This code expires in {_ttl_label(ttl_minutes)}.\n\n"
        f"If you did not request this, ignore this email.\n\n"
        f"Terra Meta by 5G Geology\n"
        f"https://5ggeology.com"
    )
