// Lazy environment configuration. Nothing here reads `process.env` at import
// time — each getter throws only when actually invoked, so unit tests that
// never touch a given config value don't need every secret set.

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

/** GitHub App id, used as the JWT `iss` claim. */
export function getGithubAppId(): string {
  return requireEnv("GITHUB_APP_ID");
}

/** GitHub App private key, PEM-encoded (PKCS#1 or PKCS#8). */
export function getGithubAppPrivateKeyPem(): string {
  return requireEnv("GITHUB_APP_PRIVATE_KEY_PEM");
}

/** SQS queue URL that trigger events are enqueued to. */
export function getWorkQueueUrl(): string {
  return requireEnv("WORK_QUEUE_URL");
}

/** DynamoDB table name for per-installation allowlist entries (PK `install_id`). */
export function getInstallationsTable(): string {
  return requireEnv("INSTALLATIONS_TABLE");
}

/** DynamoDB table name for per-repo/day budget counters (PK `pk` = `repo#date`). */
export function getBudgetsTable(): string {
  return requireEnv("BUDGETS_TABLE");
}

/** DynamoDB table name for run idempotency records (PK `run_id`). */
export function getRunsTable(): string {
  return requireEnv("RUNS_TABLE");
}

function optionalEnvInt(name: string, fallback: number): number {
  const value = process.env[name];
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Max PR-count budget slots per repo per day (default 5). */
export function getMaxPrsPerRepoPerDay(): number {
  return optionalEnvInt("MAX_PRS_PER_REPO_PER_DAY", 5);
}

/** Max reconciled dollar spend per PR (default 20). Informational ceiling for reconciliation. */
export function getMaxDollarsPerPr(): number {
  return optionalEnvInt("MAX_DOLLARS_PER_PR", 20);
}

/** ECS cluster name/ARN that the worker task runs in. */
export function getEcsCluster(): string {
  return requireEnv("ECS_CLUSTER");
}

/** ECS task definition (family:revision or ARN) for the worker task. */
export function getEcsTaskDefinition(): string {
  return requireEnv("ECS_TASK_DEFINITION");
}

/** Comma-separated subnet ids for the worker task's network configuration. */
export function getEcsSubnets(): string[] {
  return requireEnv("ECS_SUBNETS")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** Comma-separated security group ids for the worker task's network configuration. */
export function getEcsSecurityGroups(): string[] {
  return requireEnv("ECS_SECURITY_GROUPS")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** Container name within the task definition to receive environment overrides. */
export function getEcsContainerName(): string {
  return requireEnv("ECS_CONTAINER_NAME");
}
