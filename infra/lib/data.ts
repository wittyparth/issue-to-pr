import { Duration, RemovalPolicy, aws_dynamodb as dynamodb, aws_ssm as ssm, aws_sqs as sqs } from "aws-cdk-lib";
import type { Construct } from "constructs";

/**
 * Data plane for the control plane (M2.5): DynamoDB tables, SQS work queue +
 * DLQ, and SSM Parameter Store placeholders for the GitHub App credentials
 * and LLM provider keys.
 *
 * These are plain `String` SSM parameters, not `SecureString` — CloudFormation
 * cannot create SecureString parameters at all (a long-standing AWS platform
 * limitation, not a CDK gap), and Secrets Manager's per-secret $0.40/month
 * flat fee isn't worth it for this project's scale. IAM access is still
 * scoped to exactly the two roles that need each parameter (see iam.ts /
 * functions.ts), so the practical exposure is unchanged from Secrets
 * Manager for this account; the difference is these values are not
 * encrypted-at-rest with a customer KMS key.
 *
 * removalPolicy is DESTROY across the board — this is the dev/eval stack;
 * production hardening (retention, PITR) is out of scope for M2.5.
 */
export interface DataResources {
  readonly installationsTable: dynamodb.Table;
  readonly budgetsTable: dynamodb.Table;
  readonly runsTable: dynamodb.Table;
  readonly workQueue: sqs.Queue;
  readonly workDlq: sqs.Queue;
  readonly githubAppParam: ssm.StringParameter;
  readonly llmProvidersParam: ssm.StringParameter;
  readonly webhookParam: ssm.StringParameter;
}

export function createData(scope: Construct): DataResources {
  const installationsTable = new dynamodb.Table(scope, "InstallationsTable", {
    tableName: "it2pr-installations",
    partitionKey: { name: "install_id", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    removalPolicy: RemovalPolicy.DESTROY,
  });

  const budgetsTable = new dynamodb.Table(scope, "BudgetsTable", {
    tableName: "it2pr-budgets",
    partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    timeToLiveAttribute: "expiresAt",
    removalPolicy: RemovalPolicy.DESTROY,
  });

  const runsTable = new dynamodb.Table(scope, "RunsTable", {
    tableName: "it2pr-runs",
    partitionKey: { name: "run_id", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    timeToLiveAttribute: "expiresAt",
    removalPolicy: RemovalPolicy.DESTROY,
  });

  const workDlq = new sqs.Queue(scope, "WorkDlq", {
    queueName: "it2pr-work-dlq",
    encryption: sqs.QueueEncryption.SQS_MANAGED,
    retentionPeriod: Duration.days(14),
  });

  const workQueue = new sqs.Queue(scope, "WorkQueue", {
    queueName: "it2pr-work-queue",
    encryption: sqs.QueueEncryption.SQS_MANAGED,
    visibilityTimeout: Duration.minutes(5),
    deadLetterQueue: {
      queue: workDlq,
      maxReceiveCount: 5,
    },
  });

  // Placeholder parameters: no real values are seeded here. The GitHub App
  // private key + LLM provider keys are populated out-of-band after deploy
  // via `aws ssm put-parameter --overwrite`.
  const githubAppParam = new ssm.StringParameter(scope, "GithubAppParam", {
    parameterName: "/it2pr/github-app",
    description: "GitHub App ID + private key (PEM) for the Issue-to-PR control plane",
    stringValue: "PLACEHOLDER_SET_AFTER_DEPLOY",
  });
  githubAppParam.applyRemovalPolicy(RemovalPolicy.DESTROY);

  const llmProvidersParam = new ssm.StringParameter(scope, "LlmProvidersParam", {
    parameterName: "/it2pr/llm-providers",
    description: "LLM provider API keys (OpenRouter/OpenAI/Anthropic/etc.)",
    stringValue: "PLACEHOLDER_SET_AFTER_DEPLOY",
  });
  llmProvidersParam.applyRemovalPolicy(RemovalPolicy.DESTROY);

  // Dedicated parameter for the GitHub webhook HMAC signing secret. This is a
  // distinct raw string value, never the githubAppParam's `{appId,
  // privateKeyPem}` JSON blob — `verifySignature` uses the whole parameter
  // value as the HMAC key, so pointing it at the wrong parameter makes every
  // webhook delivery fail signature verification.
  const webhookParam = new ssm.StringParameter(scope, "WebhookParam", {
    parameterName: "/it2pr/webhook-secret",
    description: "GitHub webhook HMAC signing secret (raw value, not JSON)",
    stringValue: "PLACEHOLDER_SET_AFTER_DEPLOY",
  });
  webhookParam.applyRemovalPolicy(RemovalPolicy.DESTROY);

  return {
    installationsTable,
    budgetsTable,
    runsTable,
    workQueue,
    workDlq,
    githubAppParam,
    llmProvidersParam,
    webhookParam,
  };
}
