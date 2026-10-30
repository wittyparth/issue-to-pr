// Runtime resolver for secrets that must not be baked into the CDK template.
//
// The webhook Lambda needs `GH_WEBHOOK_SECRET` to verify inbound HMAC
// signatures. Rather than passing the raw secret value as a plaintext env
// var (which would land in the CloudFormation template/console), the CDK
// stack passes the *name* of the SSM Parameter Store parameter via
// `GH_WEBHOOK_PARAM_NAME` and grants the function read access. This resolver
// fetches the parameter value at runtime (once) and caches it in memory for
// the lifetime of the execution environment.
//
// These are plain `String` parameters, not `SecureString` (CloudFormation
// cannot create SecureString parameters — see infra/lib/data.ts) — swapped
// from Secrets Manager to avoid its flat $0.40/secret/month fee.
// `WithDecryption: true` is harmless for a non-encrypted String parameter.
import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";

export interface SecretResolverOptions {
  client?: SSMClient;
  /** Override the in-memory cache; primarily for test isolation. */
  cache?: Map<string, string>;
}

let defaultClient: SSMClient | undefined;

function getDefaultClient(): SSMClient {
  defaultClient ??= new SSMClient({});
  return defaultClient;
}

const secretValueCache = new Map<string, string>();

/**
 * Fetch and cache an SSM parameter's string value by name. Subsequent calls
 * for the same `parameterName` within the same process return the cached
 * value without another API call.
 */
export async function getCachedSecretValue(
  parameterName: string,
  options: SecretResolverOptions = {},
): Promise<string> {
  const cache = options.cache ?? secretValueCache;
  const cached = cache.get(parameterName);
  if (cached !== undefined) {
    return cached;
  }

  const client = options.client ?? getDefaultClient();
  const response = await client.send(
    new GetParameterCommand({ Name: parameterName, WithDecryption: true }),
  );
  const value = response.Parameter?.Value;
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Parameter ${parameterName} has no string value`);
  }

  cache.set(parameterName, value);
  return value;
}

/**
 * Resolve the GitHub webhook secret at runtime: prefer an explicit
 * `GH_WEBHOOK_SECRET` env var (useful for local/test); otherwise fetch and
 * cache the value referenced by `GH_WEBHOOK_PARAM_NAME` from SSM Parameter
 * Store.
 */
export async function resolveWebhookSecret(
  options: SecretResolverOptions = {},
): Promise<string> {
  const direct = process.env["GH_WEBHOOK_SECRET"];
  if (direct) {
    return direct;
  }

  const paramName = process.env["GH_WEBHOOK_PARAM_NAME"];
  if (!paramName) {
    throw new Error(
      "Missing required environment variable: GH_WEBHOOK_SECRET or GH_WEBHOOK_PARAM_NAME",
    );
  }

  return getCachedSecretValue(paramName, options);
}
