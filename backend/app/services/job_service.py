from app.models.job import DeploymentJob, JobType
from app.workers.celery_app import celery_app


class JobService:
    def dispatch_job(self, job: DeploymentJob) -> str:
        task_name_map = {
            JobType.BOOTSTRAP_SERVER: "app.workers.tasks.bootstrap_server",
            JobType.CHECK_SERVER: "app.workers.tasks.check_server",
            JobType.DETECT_AWG: "app.workers.tasks.detect_awg",
            JobType.DEPLOY_TOPOLOGY: "app.workers.tasks.deploy_topology",
            JobType.BACKUP: "app.workers.tasks.run_backup",
        }
        task_name = task_name_map[job.job_type]
        task = celery_app.send_task(task_name, kwargs={"job_id": job.id})
        return task.id
