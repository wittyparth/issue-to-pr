import {
  Duration,
  RemovalPolicy,
  aws_ec2 as ec2,
  aws_ecr as ecr,
  aws_ecs as ecs,
  aws_logs as logs,
} from "aws-cdk-lib";
import type { Construct } from "constructs";

/** Stable container name shared by the worker task definition and future RunTask overrides. */
export const WORKER_CONTAINER_NAME = "worker";

export interface ComputeResources {
  readonly cluster: ecs.Cluster;
  readonly workerRepository: ecr.Repository;
  readonly workerTaskDefinition: ecs.FargateTaskDefinition;
  readonly workerLogGroup: logs.LogGroup;
}

export interface LlmConfig {
  readonly provider: string;
  readonly model: string;
}

export function createCompute(
  scope: Construct,
  vpc: ec2.IVpc,
  llmConfig: LlmConfig,
): ComputeResources {
  // Fargate-only cluster — no EC2 capacity, no idle compute.
  const cluster = new ecs.Cluster(scope, "Cluster", {
    vpc,
    clusterName: "it2pr-cluster",
    containerInsightsV2: ecs.ContainerInsights.DISABLED,
  });

  const workerRepository = new ecr.Repository(scope, "WorkerRepository", {
    repositoryName: "it2pr-worker",
    imageScanOnPush: true,
    removalPolicy: RemovalPolicy.DESTROY,
    emptyOnDelete: true,
    lifecycleRules: [
      {
        description: "Expire untagged images after 3 days",
        tagStatus: ecr.TagStatus.UNTAGGED,
        maxImageAge: Duration.days(3),
      },
    ],
  });

  const workerLogGroup = new logs.LogGroup(scope, "WorkerLogGroup", {
    logGroupName: "/it2pr/worker",
    retention: logs.RetentionDays.TWO_WEEKS,
    removalPolicy: RemovalPolicy.DESTROY,
  });

  // Execution role defaults to the standard ECS task-execution managed
  // policy equivalent (ECR auth + log group creation); ECR pull perms for
  // *this* repository are granted explicitly below via grantPull (M2.5 IAM
  // wiring), not via a wildcard.
  const workerTaskDefinition = new ecs.FargateTaskDefinition(scope, "WorkerTaskDefinition", {
    family: "it2pr-worker",
    cpu: 1024,
    memoryLimitMiB: 2048,
  });

  workerTaskDefinition.addContainer(WORKER_CONTAINER_NAME, {
    containerName: WORKER_CONTAINER_NAME,
    image: ecs.ContainerImage.fromEcrRepository(workerRepository),
    logging: ecs.LogDrivers.awsLogs({
      streamPrefix: "worker",
      logGroup: workerLogGroup,
    }),
    // Static deployment-wide config (which LLM provider/model to use), not a
    // secret — the worker's llm/factory.py requires LLM_MODEL and raises a
    // clear config error without it, so this must always be set.
    environment: {
      LLM_PROVIDER: llmConfig.provider,
      LLM_MODEL: llmConfig.model,
    },
    // No secrets injected as plaintext env — the worker mints its own
    // installation token at start and reads secrets directly from Secrets
    // Manager via its task role (see iam.ts).
  });

  // Execution role needs to pull from this specific ECR repo.
  if (workerTaskDefinition.executionRole) {
    workerRepository.grantPull(workerTaskDefinition.executionRole);
  }

  return { cluster, workerRepository, workerTaskDefinition, workerLogGroup };
}
