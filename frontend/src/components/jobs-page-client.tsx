"use client";

import { useEffect, useState } from "react";

import { apiRequest } from "./api";
import { ProtectedApp } from "./protected-app";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type Job = {
  id: number;
  job_type: string;
  status: string;
  server_id: number | null;
  topology_id: number | null;
  result_message: string | null;
  task_id: string | null;
  created_at: string;
  updated_at: string;
};

export function JobsPageClient() {
  const { token, logout } = useAuth();
  const { locale } = useLocale();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const copy = locale === "ru"
    ? {
        title: "Отслеживание фоновых задач и deployment-потоков.",
        refresh: "Обновить",
        empty: "Задач пока нет.",
        server: "сервер",
        topology: "топология",
        task: "task",
        created: "создано"
      }
    : {
        title: "Track background execution and deployment tasks.",
        refresh: "Refresh",
        empty: "No jobs yet.",
        server: "server",
        topology: "topology",
        task: "task",
        created: "created"
      };

  async function loadJobs() {
    if (!token) {
      return;
    }
    try {
      const nextJobs = await apiRequest<Job[]>("/jobs", { token });
      setJobs(nextJobs);
      setError(null);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Failed to load jobs";
      setError(message);
      if (message.includes("401")) {
        logout();
      }
    }
  }

  function formatDate(value: string) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString(locale === "ru" ? "ru-RU" : "en-US");
  }

  useEffect(() => {
    void loadJobs();
    if (!token) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadJobs();
    }, 10000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  return (
    <ProtectedApp>
      <div className="page-header">
        <div>
          <span className="eyebrow">Jobs</span>
          <h2>{copy.title}</h2>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadJobs()}>
          {copy.refresh}
        </button>
      </div>

      {error ? <div className="error-box">{error}</div> : null}

      <section className="panel-card">
        <div className="job-list">
          {jobs.length === 0 ? (
            <div className="empty-state">{copy.empty}</div>
          ) : (
            jobs.map((job) => (
              <article key={job.id} className="job-card">
                <div className="server-card-header">
                  <div>
                    <h3>
                      #{job.id} {job.job_type}
                    </h3>
                    <p>
                      {copy.server}: {job.server_id ?? "-"} | {copy.topology}: {job.topology_id ?? "-"}
                    </p>
                  </div>
                  <span className={`status-badge status-${job.status}`}>{job.status}</span>
                </div>
                <div className="server-meta">
                  <span>{copy.task}: {job.task_id ?? "-"}</span>
                  <span>{copy.created}: {formatDate(job.created_at)}</span>
                </div>
                {job.result_message ? <pre className="log-box">{job.result_message}</pre> : null}
              </article>
            ))
          )}
        </div>
      </section>
    </ProtectedApp>
  );
}
