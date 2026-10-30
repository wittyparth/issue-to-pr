// GitHub App installation-token minting.
//
// Flow: build a short-lived App JWT (RS256, signed with the App's private
// key), exchange it for an installation access token via the GitHub REST
// API, and cache the result in memory per installation until it's close to
// expiry. Never log the JWT, the installation token, or the PEM.
import { importPKCS8, SignJWT } from "jose";

const JWT_TTL_SECONDS = 9 * 60; // GitHub caps App JWTs at 10 minutes; stay under.
const REFRESH_MARGIN_MS = 5 * 60 * 1000; // Re-mint when less than 5 min remains.

export interface GithubAppCredentials {
  appId: string;
  privateKeyPem: string;
}

export interface InstallationToken {
  token: string;
  expiresAt: Date;
}

interface CacheEntry {
  token: string;
  expiresAtMs: number;
}

const installationTokenCache = new Map<number, CacheEntry>();

/** Build and sign a GitHub App JWT for the given credentials. */
export async function mintAppJwt(credentials: GithubAppCredentials): Promise<string> {
  const privateKey = await importPKCS8(credentials.privateKeyPem, "RS256");
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({})
    .setProtectedHeader({ alg: "RS256" })
    .setIssuer(credentials.appId)
    .setIssuedAt(now)
    .setExpirationTime(now + JWT_TTL_SECONDS)
    .sign(privateKey);
}

export interface FetchLike {
  (input: string, init?: RequestInit): Promise<Response>;
}

interface ExchangeOptions {
  fetchImpl?: FetchLike;
}

async function exchangeForInstallationToken(
  appJwt: string,
  installationId: number,
  options: ExchangeOptions = {},
): Promise<InstallationToken> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const url = `https://api.github.com/app/installations/${installationId}/access_tokens`;
  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${appJwt}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to mint installation token: HTTP ${response.status}`);
  }

  const body = (await response.json()) as { token?: unknown; expires_at?: unknown };
  if (typeof body.token !== "string" || typeof body.expires_at !== "string") {
    throw new Error("Malformed installation access token response");
  }

  return { token: body.token, expiresAt: new Date(body.expires_at) };
}

export interface GetInstallationTokenOptions {
  fetchImpl?: FetchLike;
  /** Override the cache map; primarily for tests that want isolation. */
  cache?: Map<number, CacheEntry>;
}

/**
 * Get a valid installation access token for `installationId`, minting a new
 * one (via a fresh App JWT) if none is cached or the cached one is within
 * `REFRESH_MARGIN_MS` of expiring.
 */
export async function getInstallationToken(
  credentials: GithubAppCredentials,
  installationId: number,
  options: GetInstallationTokenOptions = {},
): Promise<InstallationToken> {
  const cache = options.cache ?? installationTokenCache;
  const cached = cache.get(installationId);
  const now = Date.now();

  if (cached && cached.expiresAtMs - now > REFRESH_MARGIN_MS) {
    return { token: cached.token, expiresAt: new Date(cached.expiresAtMs) };
  }

  const appJwt = await mintAppJwt(credentials);
  const exchangeOptions: ExchangeOptions = options.fetchImpl ? { fetchImpl: options.fetchImpl } : {};
  const result = await exchangeForInstallationToken(appJwt, installationId, exchangeOptions);

  cache.set(installationId, { token: result.token, expiresAtMs: result.expiresAt.getTime() });
  return result;
}
