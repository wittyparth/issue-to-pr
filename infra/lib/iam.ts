import { Stack, aws_dynamodb as dynamodb, aws_ecs as ecs, aws_iam as iam, aws_logs as logs, aws_ssm as ssm, aws_sqs as sqs } from "aws-cdk-lib";
import type { Construct } from "constructs";

/**
 * Least-privilege IAM wiring for the control plane (M2.5).
 *
 * No wildcard resources on secrets, DynamoDB, or ecs:RunTask. The dispatcher
 * role is scoped to RunTask + PassRole on exactly the worker task definition
 * and its two roles; it is exported here for the M6 dispatcher Lambda to
 * assume/attach.
 */
export interface IamInputs {
  readonly workerTaskDefinition: ecs.FargateTaskDefinition;
  readonly workerLogGroup: logs.LogGroup;
  readonly githubAppParam: ssm.StringParameter;
  readonly llmProvidersParam: ssm.StringParameter;
  readonly installationsTable: dynamodb.Table;
  readonly budgetsTable: dynamodb.Table;
  readonly runsTable: dynamodb.Table;
  readonly workQueue: sqs.Queue;
}

export interface IamResources {
  readonly dispatcherRole: iam.Role;
}

export function createIam(scope: Construct, inputs: IamInputs): IamResources {
  const {
    workerTaskDefinition,
    workerLogGroup,
    githubAppParam,
    llmProvidersParam,
    installationsTable,
    budgetsTable,
    runsTable,
    workQueue,
  } = inputs;

  // --- Worker task role: only what the worker needs at runtime. ---
  const taskRole = workerTaskDefinition.taskRole;

  // Read-only on exactly the two parameters it needs (App key to mint its
  // own installation token; LLM provider keys for the agent loop).
  githubAppParam.grantRead(taskRole);
  llmProvidersParam.grantRead(taskRole);

  // Read/write on the tables the worker touches directly (run state,
  // budget reconciliation). No wildcard table ARNs.
  runsTable.grantReadWriteData(taskRole);
  budgetsTable.grantReadWriteData(taskRole);

  // Explicit, scoped PutLogEvents/CreateLogStream on the worker's own log
  // group (the execution role already handles log group creation via the
  // ECS-managed policy; this covers the task role writing app-level logs).
  workerLogGroup.grantWrite(taskRole);

  // --- Dispatcher role (assumed by the future M6 dispatcher Lambda). ---
  const dispatcherRole = new iam.Role(scope, "DispatcherRole", {
    roleName: "it2pr-dispatcher",
    assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
    description: "M6 dispatcher Lambda: RunTask scoped to the worker task def only",
  });

  // RunTask scoped to exactly the worker task definition family (all
  // revisions), never "*". `taskDefinitionArn` is an unresolved CDK token at
  // synth time, so string-splitting it (as a prior version of this code did)
  // silently mangles the ARN; build it via formatArn instead.
  const taskDefinitionFamilyArn = Stack.of(scope).formatArn({
    service: "ecs",
    resource: "task-definition",
    resourceName: `${workerTaskDefinition.family}:*`,
  });
  dispatcherRole.addToPolicy(
    new iam.PolicyStatement({
      sid: "RunWorkerTaskOnly",
      actions: ["ecs:RunTask"],
      resources: [taskDefinitionFamilyArn],
    }),
  );

  // PassRole limited to exactly the worker task role + execution role —
  // never a wildcard on iam:PassRole.
  const passRoleResources = [workerTaskDefinition.taskRole.roleArn];
  if (workerTaskDefinition.executionRole) {
    passRoleResources.push(workerTaskDefinition.executionRole.roleArn);
  }
  dispatcherRole.addToPolicy(
    new iam.PolicyStatement({
      sid: "PassWorkerRolesOnly",
      actions: ["iam:PassRole"],
      resources: passRoleResources,
    }),
  );

  installationsTable.grantReadData(dispatcherRole);
  runsTable.grantReadWriteData(dispatcherRole);
  budgetsTable.grantReadWriteData(dispatcherRole);
  workQueue.grantSendMessages(dispatcherRole);

  return { dispatcherRole };
}
