import {
  Duration,
  Stack,
  aws_cloudwatch as cloudwatch,
  aws_dynamodb as dynamodb,
  aws_ecs as ecs,
  aws_iam as iam,
  aws_lambda as lambda,
  aws_sqs as sqs,
} from "aws-cdk-lib";
import { NodejsFunction, OutputFormat } from "aws-cdk-lib/aws-lambda-nodejs";
import type { BundlingOptions } from "aws-cdk-lib/aws-lambda-nodejs";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import type { aws_ec2 as ec2, aws_ssm as ssm } from "aws-cdk-lib";
import type { Construct } from "constructs";

/**
 * Lambda functions for the control plane (M6): webhook receiver, SQS
 * dispatcher, and work-queue DLQ consumer. All three are bundled from the
 * `@it2pr/app` TypeScript sources with `NodejsFunction` (esbuild), emitting
 * ESM output (matching the app package's `"type": "module"`) with the AWS
 * SDK v3 clients left external (already present in the Node 20 Lambda
 * runtime).
 */
export interface FunctionsInputs {
  readonly workQueue: sqs.Queue;
  readonly workDlq: sqs.Queue;
  readonly githubAppParam: ssm.StringParameter;
  readonly llmProvidersParam: ssm.StringParameter;
  readonly webhookParam: ssm.StringParameter;
  readonly installationsTable: dynamodb.Table;
  readonly budgetsTable: dynamodb.Table;
  readonly runsTable: dynamodb.Table;
  readonly cluster: ecs.Cluster;
  readonly workerTaskDefinition: ecs.FargateTaskDefinition;
  readonly vpc: ec2.IVpc;
  readonly workerSecurityGroup: ec2.SecurityGroup;
  readonly workerContainerName: string;
}

export interface FunctionsResources {
  readonly webhookFn: NodejsFunction;
  readonly dispatcherFn: NodejsFunction;
  readonly dlqConsumerFn: NodejsFunction;
  readonly dlqAlarm: cloudwatch.Alarm;
}

// esbuild's ESM output re-imports node builtins with a `.js`-suffixed banner
// shim only when needed; nothing else required here for the Node 20 Lambda
// runtime, which supports top-level `import`.
function nodejsBundling(): BundlingOptions {
  return {
    format: OutputFormat.ESM,
    externalModules: ["@aws-sdk/*"],
    mainFields: ["module", "main"],
  };
}

export function createFunctions(scope: Construct, inputs: FunctionsInputs): FunctionsResources {
  const {
    workQueue,
    workDlq,
    githubAppParam,
    llmProvidersParam,
    webhookParam,
    installationsTable,
    budgetsTable,
    runsTable,
    cluster,
    workerTaskDefinition,
    workerSecurityGroup,
    workerContainerName,
  } = inputs;

  // --- webhookFn: API Gateway -> HMAC verify -> enqueue to workQueue. ---
  const webhookFn = new NodejsFunction(scope, "WebhookFunction", {
    functionName: "it2pr-webhook",
    entry: "../app/src/webhook/handler.ts",
    handler: "handler",
    runtime: lambda.Runtime.NODEJS_22_X,
    timeout: Duration.seconds(10),
    bundling: nodejsBundling(),
    environment: {
      WORK_QUEUE_URL: workQueue.queueUrl,
      GH_WEBHOOK_PARAM_NAME: webhookParam.parameterName,
    },
  });
  workQueue.grantSendMessages(webhookFn);
  webhookParam.grantRead(webhookFn);

  // --- dispatcherFn: SQS-triggered; idempotency + allowlist + budget + RunTask. ---
  const dispatcherFn = new NodejsFunction(scope, "DispatcherFunction", {
    functionName: "it2pr-dispatcher",
    entry: "../app/src/dispatcher/handler.ts",
    handler: "handler",
    runtime: lambda.Runtime.NODEJS_22_X,
    timeout: Duration.seconds(30),
    bundling: nodejsBundling(),
    environment: {
      INSTALLATIONS_TABLE: installationsTable.tableName,
      BUDGETS_TABLE: budgetsTable.tableName,
      RUNS_TABLE: runsTable.tableName,
      ECS_CLUSTER: cluster.clusterArn,
      ECS_TASK_DEFINITION: workerTaskDefinition.taskDefinitionArn,
      ECS_SUBNETS: inputs.vpc.publicSubnets.map((subnet) => subnet.subnetId).join(","),
      ECS_SECURITY_GROUPS: workerSecurityGroup.securityGroupId,
      ECS_CONTAINER_NAME: workerContainerName,
      // Passed through as informational env so the worker (launched by
      // RunTask) can be pointed at the same parameters without the
      // dispatcher ever reading their values itself.
      GITHUB_APP_PARAM_NAME: githubAppParam.parameterName,
      LLM_PROVIDERS_PARAM_NAME: llmProvidersParam.parameterName,
    },
  });

  installationsTable.grantReadData(dispatcherFn);
  runsTable.grantReadWriteData(dispatcherFn);
  budgetsTable.grantReadWriteData(dispatcherFn);

  // RunTask scoped to exactly the worker task-definition family (all
  // revisions) — never a wildcard. `taskDefinitionArn` is an unresolved CDK
  // token at synth time, so string-splitting it silently mangles the ARN;
  // build it via formatArn instead.
  dispatcherFn.addToRolePolicy(
    new iam.PolicyStatement({
      sid: "RunWorkerTaskOnly",
      actions: ["ecs:RunTask"],
      resources: [
        Stack.of(scope).formatArn({
          service: "ecs",
          resource: "task-definition",
          resourceName: `${workerTaskDefinition.family}:*`,
        }),
      ],
    }),
  );

  // PassRole limited to exactly the worker task role + execution role.
  const passRoleResources = [workerTaskDefinition.taskRole.roleArn];
  if (workerTaskDefinition.executionRole) {
    passRoleResources.push(workerTaskDefinition.executionRole.roleArn);
  }
  dispatcherFn.addToRolePolicy(
    new iam.PolicyStatement({
      sid: "PassWorkerRolesOnly",
      actions: ["iam:PassRole"],
      resources: passRoleResources,
    }),
  );

  dispatcherFn.addEventSource(
    new SqsEventSource(workQueue, {
      // batchSize 1 so budget/idempotency reservation is evaluated per
      // message, never batched across multiple runs.
      batchSize: 1,
    }),
  );

  // --- dlqConsumerFn: work-queue DLQ -> structured log + issue comment. ---
  const dlqConsumerFn = new NodejsFunction(scope, "DlqConsumerFunction", {
    functionName: "it2pr-dlq-consumer",
    entry: "../app/src/dlq/handler.ts",
    handler: "handler",
    runtime: lambda.Runtime.NODEJS_22_X,
    timeout: Duration.seconds(15),
    bundling: nodejsBundling(),
    environment: {
      GITHUB_APP_PARAM_NAME: githubAppParam.parameterName,
    },
  });
  githubAppParam.grantRead(dlqConsumerFn);
  dlqConsumerFn.addEventSource(
    new SqsEventSource(workDlq, {
      batchSize: 1,
    }),
  );

  // Terminal failures must never swallow silently: alarm the instant any
  // message lands in the DLQ, independent of whether the consumer's
  // best-effort issue comment succeeds.
  const dlqAlarm = new cloudwatch.Alarm(scope, "WorkDlqAlarm", {
    alarmName: "it2pr-work-dlq-not-empty",
    alarmDescription: "Terminal-failure messages present in the work-queue DLQ",
    metric: workDlq.metricApproximateNumberOfMessagesVisible({
      period: Duration.minutes(1),
      statistic: "Maximum",
    }),
    threshold: 0,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 1,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  });

  return { webhookFn, dispatcherFn, dlqConsumerFn, dlqAlarm };
}
