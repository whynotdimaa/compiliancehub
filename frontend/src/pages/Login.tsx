import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../api";
import { useAuth } from "../App";
import { Spinner } from "../components/ui";

export function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [slug, setSlug] = useState("demo");
  const [email, setEmail] = useState("admin@demo.io");
  const [password, setPassword] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [fullName, setFullName] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.register({
          tenant_name: tenantName,
          tenant_slug: slug,
          admin_email: email,
          admin_password: password,
          admin_full_name: fullName,
        });
      }
      const tokens = await api.login({ tenant_slug: slug, email, password });
      await signIn(tokens.access_token);
      navigate("/documents");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-brand">
        <div className="wordmark">ComplianceHub</div>
        <div>
          <h1>
            Audit-grade answers from <em>your own</em> policies.
          </h1>
          <p className="tagline">
            Upload contracts, standards and internal policies. Ask questions in plain language —
            every answer arrives with citations down to the section and page.
          </p>
          <div className="auth-points">
            <div className="auth-point">
              <span className="idx">01</span>
              <span><b>Hybrid retrieval.</b> Vector, full-text and knowledge-graph search, fused and reranked.</span>
            </div>
            <div className="auth-point">
              <span className="idx">02</span>
              <span><b>Corrective agent.</b> Irrelevant context is graded out before an answer is written.</span>
            </div>
            <div className="auth-point">
              <span className="idx">03</span>
              <span><b>Measured quality.</b> Faithfulness and recall scored on a golden dataset, not vibes.</span>
            </div>
          </div>
        </div>
        <span className="microlabel">Multi-tenant · Row-level security · PII masked before any LLM</span>
      </section>

      <section className="auth-form-side">
        <form className="auth-card" onSubmit={submit}>
          <div>
            <h2>{mode === "signin" ? "Sign in" : "Create a workspace"}</h2>
          </div>
          {mode === "register" && (
            <div className="field">
              <label>Organization name</label>
              <input className="input" value={tenantName} onChange={(e) => setTenantName(e.target.value)} required minLength={2} placeholder="Acme Corp" />
            </div>
          )}
          <div className="field">
            <label>Workspace slug</label>
            <input
              className="input"
              value={slug}
              onChange={(e) =>
                setSlug(e.target.value.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, ""))
              }
              required
              minLength={2}
              placeholder="acme"
            />
            {mode === "register" && (
              <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
                Lowercase letters, numbers and dashes — this identifies your workspace at sign-in.
              </span>
            )}
          </div>
          {mode === "register" && (
            <div className="field">
              <label>Your name</label>
              <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Doe" />
            </div>
          )}
          <div className="field">
            <label>Email</label>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label>Password</label>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </div>
          {error && <div className="error-note">{error}</div>}
          <button className="btn btn-primary" disabled={busy} style={{ justifyContent: "center" }}>
            {busy ? <Spinner /> : mode === "signin" ? "Sign in" : "Create workspace"}
          </button>
          <div className="auth-switch">
            {mode === "signin" ? (
              <>New here? <button type="button" onClick={() => setMode("register")}>Create a workspace</button></>
            ) : (
              <>Already registered? <button type="button" onClick={() => setMode("signin")}>Sign in</button></>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
