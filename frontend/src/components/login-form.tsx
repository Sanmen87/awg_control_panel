"use client";

import { FormEvent, useState } from "react";

import { apiRequest } from "./api";
import { useAuth } from "./auth-context";
import { useLocale } from "./locale-context";

type LoginResponse = {
  access_token: string;
  token_type: string;
};

export function LoginForm() {
  const { setToken } = useAuth();
  const { locale } = useLocale();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const copy = locale === "ru"
    ? {
        title: "Вход в панель управления серверами и задачами.",
        username: "Логин",
        password: "Пароль",
        showPassword: "Показать пароль",
        hidePassword: "Скрыть пароль",
        submit: "Войти",
        submitting: "Вход..."
      }
    : {
        title: "Sign in to manage servers and jobs.",
        username: "Username",
        password: "Password",
        showPassword: "Show password",
        hidePassword: "Hide password",
        submit: "Sign in",
        submitting: "Signing in..."
      };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await apiRequest<LoginResponse>("/auth/login", {
        method: "POST",
        body: { username, password }
      });
      setToken(response.access_token);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="auth-card" onSubmit={handleSubmit}>
      <span className="eyebrow">Admin Login</span>
      <h2>{copy.title}</h2>
      <label className="field">
        <span>{copy.username}</span>
        <input value={username} onChange={(event) => setUsername(event.target.value)} />
      </label>
      <label className="field">
        <span>{copy.password}</span>
        <div className="password-field">
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button
            type="button"
            className="toggle-visibility icon-toggle"
            onClick={() => setShowPassword((value) => !value)}
            aria-label={showPassword ? copy.hidePassword : copy.showPassword}
            title={showPassword ? copy.hidePassword : copy.showPassword}
          >
            {showPassword ? "🙈" : "👁"}
          </button>
        </div>
      </label>
      {error ? <div className="error-box">{error}</div> : null}
      <button type="submit" className="primary-button" disabled={loading}>
        {loading ? copy.submitting : copy.submit}
      </button>
    </form>
  );
}
