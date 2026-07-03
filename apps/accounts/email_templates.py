from .email_branding import email_layout_html


def _ttl_label(minutes: int) -> str:
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {unit}"


def otp_email_html(code: str, purpose: str, ttl_minutes: int) -> str:
    action = "sign in" if purpose == "login" else "verify your email"
    body = f"""
              <p style="margin:0 0 20px;font-size:15px;line-height:1.65;color:#475569;text-align:center;">
                Use this code to {action}. It expires in <strong style="color:#1e3a2f;">{_ttl_label(ttl_minutes)}</strong>.
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center" style="background:linear-gradient(180deg,#f0fdf4 0%,#ecfdf5 100%);border:1px solid #bbf7d0;border-radius:16px;padding:28px 20px;">
                    <p style="margin:0 0 10px;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#166534;">Verification code</p>
                    <p style="margin:0;font-size:34px;font-weight:800;letter-spacing:0.28em;color:#14532d;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;">{code}</p>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:#94a3b8;text-align:center;">
                If you did not request this code, you can safely ignore this email.
              </p>"""
    return email_layout_html(
        title="Terra Meta verification code",
        heading="Your verification code",
        body_html=body,
    )


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


def subscription_reminder_html(name: str, plan_name: str, end_date, days_left: int, renew_url: str) -> str:
    body = f"""
              <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#475569;">
                Hello {name},
              </p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#475569;">
                Your <strong>{plan_name}</strong> subscription renews in <strong>{days_left} day(s)</strong>
                (expires {end_date}).
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <a href="{renew_url}" style="display:inline-block;background:#2d5a47;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:14px 28px;border-radius:12px;">
                      Renew subscription
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:#94a3b8;text-align:center;">
                Keep full access to mineral maps, reports, and analytics.
              </p>"""
    return email_layout_html(
        title="Terra Meta subscription reminder",
        heading="Subscription renewal reminder",
        body_html=body,
    )


def subscription_reminder_text(name: str, plan_name: str, end_date, days_left: int, renew_url: str) -> str:
    return (
        f"Hello {name},\n\n"
        f"Your {plan_name} subscription renews in {days_left} day(s) (expires {end_date}).\n\n"
        f"Renew now to keep full access: {renew_url}\n\n"
        f"Terra Meta by 5G Geology\n"
        f"https://5ggeology.com"
    )
