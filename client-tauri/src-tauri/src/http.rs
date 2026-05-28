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
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("reqwest client build")
}

/// Call once at startup (or after the user logs out) to rotate the underlying
/// connection pool + cookie jar.
pub fn refresh(_state: &ConfigState) {
    *CLIENT_CELL.write() = Some(Arc::new(build()));
}

pub fn client(_state: &ConfigState) -> Arc<Client> {
    if let Some(c) = CLIENT_CELL.read().clone() {
        return c;
    }
    let c = Arc::new(build());
    *CLIENT_CELL.write() = Some(c.clone());
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
