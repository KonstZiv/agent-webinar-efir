"""Services of the feature Ф1 by key (``app.services``), named ``referral.*``."""

from app.core.referral.ports import ReferralStore
from app.core.referral.service import Referrals
from app.services import Key

STORE = Key[ReferralStore]("referral.store")
REFERRALS = Key[Referrals]("referral.scenario")
