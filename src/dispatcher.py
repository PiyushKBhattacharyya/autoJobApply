from typing import Any, Dict, Optional
from src.applier import NaukriApplier
from src.indeed_applier import IndeedApplier
from src.linkedin_applier import LinkedInApplier


class UnifiedApplier:
    """Dispatches application requests to the correct platform handler."""
    def __init__(self):
        self.naukri_applier = NaukriApplier()
        self._indeed_applier = None
        self._linkedin_applier = None

    @property
    def indeed_applier(self):
        if self._indeed_applier is None:
            self._indeed_applier = IndeedApplier()
        return self._indeed_applier

    @property
    def linkedin_applier(self):
        if self._linkedin_applier is None:
            self._linkedin_applier = LinkedInApplier()
        return self._linkedin_applier

    def apply_to_job(
        self,
        job: Dict[str, Any],
        resume_path: Optional[str] = None,
        easy_apply_only: bool = False,
        interactive: bool = True
    ) -> str:
        platform = (job.get("platform") or "naukri").lower()

        if platform == "indeed":
            return self.indeed_applier.apply_to_job(
                job, resume_path=resume_path, easy_apply_only=easy_apply_only, interactive=interactive
            )
        elif platform == "linkedin":
            return self.linkedin_applier.apply_to_job(
                job, resume_path=resume_path, easy_apply_only=easy_apply_only, interactive=interactive
            )
        else:
            return self.naukri_applier.apply_to_job(
                job, resume_path=resume_path, easy_apply_only=easy_apply_only, interactive=interactive
            )
