# CragPal privacy retention runbook

Effective date: 2026-09-18.

This runbook covers the production API request logs and support mail described
in the CragPal App privacy policy. It does not change field-test evidence or
wall-package release gates.

## Production network and runtime logs

Nginx is the authoritative entrance proxy. Its access log contains the client
IP address, request time, resource path, response status, and user agent. The
production configuration in `deploy/logrotate/nginx` rotates these files daily,
compresses old files, and retains 190 rotations. This preserves relevant
network logs for at least six months. Older rotations are deleted automatically
unless a documented legal, security-incident, or dispute hold applies.

The API container emits request and error output. Docker limits its local
`json-file` logs to five 10 MB files. Systemd journals the attached service and
uses `deploy/systemd/90-cragpal-retention.conf`: 190-day maximum age, 8 GB
maximum use, 10 GB free-space floor, and one-day journal files. These runtime
logs assist diagnosis; the Nginx access log remains the required durable
network-request record.

Only operators who need the logs for service delivery, security, incident
response, or legal duties may access them. Logs are not used for advertising or
cross-service tracking.

## Support email

Support is initiated by the user through `z.zhang020@gmail.com`. A support
message may contain the sender address, problem description, and attachments
the sender chooses to include. Close a request after the issue is answered or
the user stops responding. Review and delete resolved messages and attachments
within 12 months after the last communication, unless a documented legal,
security-incident, or dispute hold applies.

Run the mailbox review at least quarterly. Record the review date, the cutoff
date, the number of resolved conversations deleted, and any held conversations
without copying message contents into the record.

## Requests and withdrawal

A user may withdraw App privacy consent in the App and may request access,
correction, or deletion through the support address. Verify enough information
to avoid acting on another person's data. Delete support material that is not
subject to a hold. Network logs required by applicable law remain until their
required period ends; explain that limit when responding. Do not claim that
uninstalling the App deletes server logs or email.

## Verification after a production change

1. Confirm `/etc/logrotate.d/nginx` is root-owned and says `daily` and
   `rotate 190`; run Logrotate in debug mode.
2. Confirm the API unit includes Docker `max-size=10m` and `max-file=5`.
3. Confirm Journald's merged configuration reports `MaxRetentionSec=190day`,
   `SystemMaxUse=8G`, `SystemKeepFree=10G`, and `MaxFileSec=1day`.
4. Confirm both the local and public HTTPS `/health` endpoints return OK after
   any API restart.
5. Reconcile the public policy, in-App policy, privacy manifest, and App Store
   Connect answers before selecting a build for review.
