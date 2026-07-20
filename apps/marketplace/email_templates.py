from apps.accounts.email_branding import email_layout_html


def _escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def marketplace_message_html(
    *,
    heading: str,
    intro: str,
    listing_title: str = "",
    message_preview: str,
    action_label: str,
    action_url: str,
) -> str:
    listing_block = ""
    if listing_title:
        listing_block = f"""
                    <p style="margin:0 0 8px;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#64748b;">Listing</p>
                    <p style="margin:0 0 12px;font-size:16px;font-weight:700;color:#0f172a;">{_escape(listing_title)}</p>"""
    body = f"""
              <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#475569;">
                {intro}
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 20px;">
                <tr>
                  <td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px 18px;">
                    {listing_block}
                    <p style="margin:0;font-size:14px;line-height:1.65;color:#334155;white-space:pre-wrap;">{_escape(message_preview)}</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <a href="{action_url}" style="display:inline-block;background:#2d5a47;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:14px 28px;border-radius:12px;">
                      {action_label}
                    </a>
                  </td>
                </tr>
              </table>"""
    return email_layout_html(title=heading, heading=heading, body_html=body)


def marketplace_inquiry_html(
    *,
    heading: str,
    listing_title: str,
    sender_name: str,
    sender_username: str,
    sender_email: str,
    sender_organization: str,
    message_preview: str,
    inbox_url: str,
    listing_url: str,
) -> str:
    org_line = ""
    if sender_organization:
        org_line = f"""
                      <tr>
                        <td style="padding:0 0 6px;font-size:13px;color:#64748b;">Organization</td>
                        <td style="padding:0 0 6px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;">{_escape(sender_organization)}</td>
                      </tr>"""

    body = f"""
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 18px;">
                <tr>
                  <td align="center">
                    <span style="display:inline-block;background:#ecfdf5;color:#166534;font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;padding:6px 12px;border-radius:999px;border:1px solid #bbf7d0;">
                      Marketplace listing inquiry
                    </span>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 18px;font-size:15px;line-height:1.65;color:#475569;text-align:center;">
                Someone reached out through your public listing on <strong>Terra Meta Marketplace</strong>.
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px;">
                <tr>
                  <td style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:16px;padding:18px 20px;">
                    <p style="margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#15803d;">Your listing</p>
                    <p style="margin:0;font-size:18px;font-weight:700;color:#14532d;line-height:1.35;">{_escape(listing_title)}</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px;">
                <tr>
                  <td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:18px 20px;">
                    <p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#64748b;">From</p>
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td style="padding:0 0 6px;font-size:13px;color:#64748b;">Name</td>
                        <td style="padding:0 0 6px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;">{_escape(sender_name)}</td>
                      </tr>
                      <tr>
                        <td style="padding:0 0 6px;font-size:13px;color:#64748b;">Username</td>
                        <td style="padding:0 0 6px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;">@{_escape(sender_username)}</td>
                      </tr>
                      {org_line}
                      <tr>
                        <td style="padding:0;font-size:13px;color:#64748b;">Email</td>
                        <td style="padding:0;font-size:13px;color:#2d5a47;font-weight:600;text-align:right;">
                          <a href="mailto:{_escape(sender_email)}" style="color:#2d5a47;text-decoration:none;">{_escape(sender_email)}</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 22px;">
                <tr>
                  <td style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #2d5a47;border-radius:14px;padding:16px 18px;">
                    <p style="margin:0 0 8px;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#64748b;">Message</p>
                    <p style="margin:0;font-size:14px;line-height:1.7;color:#334155;white-space:pre-wrap;">{_escape(message_preview)}</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 10px;">
                <tr>
                  <td align="center">
                    <a href="{inbox_url}" style="display:inline-block;background:#2d5a47;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:14px 28px;border-radius:12px;">
                      Reply in Messages
                    </a>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <a href="{listing_url}" style="display:inline-block;color:#2d5a47;text-decoration:none;font-weight:600;font-size:14px;">
                      View listing on Marketplace →
                    </a>
                  </td>
                </tr>
              </table>"""
    return email_layout_html(title=heading, heading=heading, body_html=body)


def marketplace_message_text(
    *,
    heading: str,
    intro: str,
    listing_title: str = "",
    message_preview: str,
    action_label: str,
    action_url: str,
) -> str:
    plain_intro = intro.replace("<strong>", "").replace("</strong>", "")
    listing_line = f"Listing: {listing_title}\n\n" if listing_title else ""
    return (
        f"{heading}\n\n"
        f"{plain_intro}\n\n"
        f"{listing_line}"
        f"{message_preview}\n\n"
        f"{action_label}: {action_url}\n\n"
        f"Terra Meta by 5G Geology Futures\n"
        f"https://5ggeology.com"
    )


def marketplace_inquiry_text(
    *,
    heading: str,
    listing_title: str,
    sender_name: str,
    sender_username: str,
    sender_email: str,
    sender_organization: str,
    message_preview: str,
    inbox_url: str,
    listing_url: str,
) -> str:
    org_line = f"Organization: {sender_organization}\n" if sender_organization else ""
    return (
        f"{heading}\n\n"
        f"Marketplace listing inquiry\n\n"
        f"Someone contacted you through your public Terra Meta listing.\n\n"
        f"Listing: {listing_title}\n\n"
        f"From: {sender_name} (@{sender_username})\n"
        f"{org_line}"
        f"Email: {sender_email}\n\n"
        f"Message:\n{message_preview}\n\n"
        f"Reply in Messages: {inbox_url}\n"
        f"View listing: {listing_url}\n\n"
        f"Terra Meta by 5G Geology Futures\n"
        f"https://5ggeology.com"
    )
