from django.conf import settings


def email_icon_url() -> str:
    custom = getattr(settings, "EMAIL_LOGO_URL", "").strip()
    if custom:
        return custom
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/terrameta-logo-icon.png"


def email_wordmark_url() -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/logo-word.png"


def _brand_header_html(home: str) -> str:
    icon = email_icon_url()
    return f"""
              <table role="presentation" cellspacing="0" cellpadding="0" align="center" style="margin:0 auto;">
                <tr>
                  <td style="vertical-align:middle;padding-right:14px;">
                    <a href="{home}" style="text-decoration:none;display:block;line-height:0;">
                      <img
                        src="{icon}"
                        alt=""
                        width="52"
                        height="52"
                        style="display:block;width:52px;height:52px;border:0;border-radius:14px;"
                      />
                    </a>
                  </td>
                  <td style="vertical-align:middle;text-align:left;">
                    <a href="{home}" style="text-decoration:none;display:block;">
                      <span style="font-size:26px;font-weight:800;font-style:italic;letter-spacing:-0.03em;line-height:1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                        <span style="color:#22c55e;">Terra</span><span style="color:#2563eb;">Meta</span>
                      </span>
                    </a>
                  </td>
                </tr>
              </table>"""


def email_layout_html(*, title: str, heading: str, body_html: str) -> str:
    home = settings.FRONTEND_URL.rstrip("/")
    brand = _brand_header_html(home)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#eef2f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f6;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:480px;background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 8px 32px rgba(15,23,42,0.08);">
          <tr>
            <td style="padding:28px 32px 22px;text-align:center;background:#ffffff;border-bottom:1px solid #e2e8f0;">
              {brand}
            </td>
          </tr>
          <tr>
            <td style="padding:10px 32px 0;text-align:center;background:#ffffff;">
              <h1 style="margin:0;font-size:20px;font-weight:700;color:#1e3a2f;line-height:1.35;">{heading}</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 32px 32px;">
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
              <p style="margin:0;font-size:12px;color:#64748b;line-height:1.6;">
                <strong style="color:#1e3a2f;">Terra Meta</strong> by
                <a href="https://5ggeology.com" style="color:#2d5a47;text-decoration:none;font-weight:600;">5G Geology</a><br />
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


def email_logo_url() -> str:
    return email_icon_url()
