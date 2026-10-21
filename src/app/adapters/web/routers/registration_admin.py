"""``POST /admin/emails/retry``: resend failed invitations (requirements, sections 6 and 8).

Behind the admin token (``AdminDep``); the answer is ``{"attempted", "sent", "failed"}`` as in
v1, never cached or indexed; a database outage is 503 ``{"status": "unavailable"}``. Only v2's
``lesson_invitation`` is resent: v1's ``confirmation`` is v1's to send. The retry runs on a mail
thread (``MailWorkers``), so the site never sends more than two letters at once.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.adapters.registration.keys import INVITATION, MAIL_WORKERS
from app.adapters.registration.mail import MailWorkers
from app.adapters.web.admin_auth import AdminDep
from app.adapters.web.dependencies import service
from app.adapters.web.headers import SERVICE
from app.core.ports import StorageUnavailable
from app.core.registration.invitation import InvitationDelivery

router = APIRouter()

InvitationDep = Annotated[InvitationDelivery, Depends(service(INVITATION))]
MailWorkersDep = Annotated[MailWorkers, Depends(service(MAIL_WORKERS))]


@router.post("/admin/emails/retry")
async def retry_emails(
    _: AdminDep, invitation: InvitationDep, workers: MailWorkersDep
) -> JSONResponse:
    try:
        report = await workers.run(invitation.retry_failed)
    except StorageUnavailable:
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=SERVICE)
    return JSONResponse(
        {"attempted": report.attempted, "sent": report.sent, "failed": report.failed},
        headers=SERVICE,
    )
