# Resend Email Setup Playbook

HTTP-based transactional email via [Resend](https://resend.com). Works on hosts that block outbound SMTP ports (25, 465, 587) — e.g., DigitalOcean VPS.

## Prerequisites

- Domain with DNS access (Route 53 or similar)
- Resend account at https://resend.com

## 1. Create Resend API Key

1. Go to https://resend.com/api-keys
2. Create an API key (sending access, restrict to your domain once verified)
3. Save the key — it's shown only once

## 2. Add Domain in Resend

1. Go to https://resend.com/domains → Add Domain
2. Enter: `{{domain_name}}`
3. Resend provides 4 DNS records to add

## 3. Configure DNS Records

Add these records to your DNS provider (values come from Resend dashboard):

| Type | Name | Value |
|------|------|-------|
| TXT | `resend._domainkey.{{domain_name}}` | *(DKIM key from Resend)* |
| MX | `send.{{domain_name}}` | `10 feedback-smtp.us-east-1.amazonses.com` |
| TXT | `send.{{domain_name}}` | `v=spf1 include:amazonses.com ~all` |
| TXT | `_dmarc.{{domain_name}}` | `v=DMARC1; p=none;` |

### Route 53 CLI Example

```sh
# Source AWS credentials
source {{aws_credentials_path}}

aws route53 change-resource-record-sets \
  --hosted-zone-id {{hosted_zone_id}} \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "resend._domainkey.{{domain_name}}",
          "Type": "TXT",
          "TTL": 300,
          "ResourceRecords": [{"Value": "\"{{dkim_value}}\""}]
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "send.{{domain_name}}",
          "Type": "MX",
          "TTL": 300,
          "ResourceRecords": [{"Value": "10 feedback-smtp.us-east-1.amazonses.com"}]
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "send.{{domain_name}}",
          "Type": "TXT",
          "TTL": 300,
          "ResourceRecords": [{"Value": "\"v=spf1 include:amazonses.com ~all\""}]
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "_dmarc.{{domain_name}}",
          "Type": "TXT",
          "TTL": 300,
          "ResourceRecords": [{"Value": "\"v=DMARC1; p=none;\""}]
        }
      }
    ]
  }'
```

## 4. Verify Domain

Wait for DNS propagation (usually 1–5 minutes for Route 53), then click "Verify" in the Resend dashboard.

## 5. Application Configuration

Add to your app's `.env`:

```
{{env_prefix}}RESEND_API_KEY=re_xxxxx
{{env_prefix}}EMAIL_FROM={{from_address}}
{{env_prefix}}BASE_URL=https://{{domain_name}}
```

`BASE_URL` is required so email links (e.g., password reset) point to the correct public URL. Without it, links may use `localhost` when behind a reverse proxy.

The app should:
- Use `httpx.post("https://api.resend.com/emails", ...)` with Bearer auth
- Send emails in a background thread to avoid blocking the request
- Fall back to logging the reset URL if no API key is configured

## 6. Deploy

Update the `.env` on the production host and restart the app container.

## Why Not SMTP?

Many cloud VPS providers (DigitalOcean, some AWS configs) block outbound SMTP ports by default to prevent spam. Resend uses HTTPS (port 443), which is always open.
