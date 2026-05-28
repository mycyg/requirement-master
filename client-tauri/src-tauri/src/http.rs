//! Shared reqwest client + auth header helper.
//!
//! Key design: there is a *single* long-lived `Client` for the whole process so
//! the in-memory cookie jar (populated by `/api/auth/identify`'s `Set-Cookie`)
//! persists across every command and background task. The worker
//! `X-YQGL-Client-Token` header is **not** baked into `default_headers` (that
//! would force us to rebuild the Client and drop the cookies); instead each
//! caller does `req.headers(http::auth_headers(state))` right before `.send()`.

use std::sync::Arc;

use once_cell::sync::Lazy;
use parking_lot::RwLock;
use reqwest::{header::{HeaderMap, HeaderName, HeaderValue}, Client, ClientBuilder, RequestBuilder};

use crate::config::ConfigState;

static CLIENT_CELL: Lazy<RwLock<Option<Arc<Client>>>> = Lazy::new(|| RwLock::new(None));

fn build() -> Client {
    ClientBuilder::new()
        .cookie_store(true)
        .connect_timeout(std::time::Duration::from_secs(10))
        .timeout(std::time::Duration::from_secs(120))
        .user_agent(concat!("yqgl-client/", env!("CARGO_PKG_VERSION")))
        .pool_max_idle_per_host(8)
        .build()
        .expect("reqwest client build")
}

/// Call once at startup (or after the user logs out) to rotate the underlying
/// connection pool + cookie jar.
#[allow(dead_code)]
pub fn refresh(_state: &ConfigState) {
    *CLIENT_CELL.write() = Some(Arc::new(build()));
}

pub fn client(_state: &ConfigState) -> Arc<Client> {
    // Fast path under read lock.
    if let Some(c) = CLIENT_CELL.read().clone() {
        return c;
    }
    // Slow path: upgrade to write and re-check (double-checked init).
    // Without the re-check, two concurrent callers could both observe
    // None under separate read locks, both call build(), both write
    // — and one ends up with an Arc<Client> that's not the canonical
    // one stored in CLIENT_CELL, so any Set-Cookie it received is lost
    // (cookies live on the jar inside the discarded Client). SSE +
    // reminders both spawn in setup() before any UI command runs, so
    // this race is reachable on every cold start.
    let mut guard = CLIENT_CELL.write();
    if let Some(c) = guard.as_ref() {
        return c.clone();
    }
    let c = Arc::new(build());
    *guard = Some(c.clone());
    c
}

/// Build the worker auth headers (X-YQGL-Client-Token) from the current config.
/// Empty when the user hasn't registered a device yet.
pub fn auth_headers(state: &ConfigState) -> HeaderMap {
    let mut headers = HeaderMap::new();
    let token = state.read().client_token;
    if !token.is_empty() {
        if let Ok(v) = HeaderValue::from_str(&token) {
            headers.insert(HeaderName::from_static("x-yqgl-client-token"), v);
        }
    }
    headers
}

/// Convenience: take any `RequestBuilder`, attach the worker auth header.
pub fn with_auth(req: RequestBuilder, state: &ConfigState) -> RequestBuilder {
    req.headers(auth_headers(state))
}

pub fn base_url(state: &ConfigState) -> String {
    state.read().base_url()
}

pub fn url(state: &ConfigState, path: &str) -> String {
    let base = base_url(state);
    if path.starts_with('/') {
        format!("{base}{path}")
    } else {
        format!("{base}/{path}")
    }
}
