import { CfnOutput, Stack, type StackProps } from "aws-cdk-lib";
import type { Construct } from "constructs";
import { createApi } from "./api.js";
import { createCompute, WORKER_CONTAINER_NAME, type LlmConfig } from "./compute.js";
import { createData } from "./data.js";
import { createFunctions } from "./functions.js";
import { createIam } from "./iam.js";
import { createNetwork } from "./network.js";

export interface It2prStackProps extends StackProps {
  /** Which LLM provider/model the worker uses; required, no silent default at the CDK layer. */
  readonly llmConfig: LlmConfig;
}

/**
 * Root stack for the Issue-to-PR control plane.
 *
 * M2.5 ships networking + data plane + IAM: public-subnet-only VPC (zero
 * NAT gateways), DynamoDB tables, SQS work queue, Secrets Manager
 * placeholders, an ECS/Fargate cluster + worker task definition, and
 * least-privilege IAM for the worker and future dispatcher.
 *
 * M6 adds the Lambda functions (webhook receiver, SQS dispatcher, work-queue
 * DLQ consumer + CloudWatch alarm) and the HTTP API Gateway front door,
 * fully wiring the M2.5 resources into a deployable stack.
 */
export class It2prStack extends Stack {
  constructor(scope: Construct, id: string, props: It2prStackProps) {
    super(scope, id, props);

    const { vpc, workerSecurityGroup } = createNetwork(this);

    const {
      installationsTable,
      budgetsTable,
      runsTable,
      workQueue,
      workDlq,
      githubAppParam,
      llmProvidersParam,
      webhookParam,
    } = createData(this);

    const { cluster, workerRepository, workerTaskDefinition, workerLogGroup } = createCompute(
      this,
      vpc,
      props.llmConfig,
    );

    createIam(this, {
      workerTaskDefinition,
      workerLogGroup,
      githubAppParam,
      llmProvidersParam,
      installationsTable,
      budgetsTable,
      runsTable,
      workQueue,
    });

    const { webhookFn, dispatcherFn, dlqConsumerFn } = createFunctions(this, {
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
      vpc,
      workerSecurityGroup,
      workerContainerName: WORKER_CONTAINER_NAME,
    });

    createApi(this, webhookFn);

    new CfnOutput(this, "WorkQueueUrl", { value: workQueue.queueUrl });
    new CfnOutput(this, "WorkDlqUrl", { value: workDlq.queueUrl });
    new CfnOutput(this, "InstallationsTableName", { value: installationsTable.tableName });
    new CfnOutput(this, "BudgetsTableName", { value: budgetsTable.tableName });
    new CfnOutput(this, "RunsTableName", { value: runsTable.tableName });
    new CfnOutput(this, "ClusterName", { value: cluster.clusterName });
    new CfnOutput(this, "WorkerTaskDefinitionFamily", {
      value: workerTaskDefinition.family,
    });
    new CfnOutput(this, "WorkerRepositoryUri", { value: workerRepository.repositoryUri });
    new CfnOutput(this, "VpcPublicSubnetIds", {
      value: vpc.publicSubnets.map((subnet) => subnet.subnetId).join(","),
    });
    new CfnOutput(this, "WorkerSecurityGroupId", {
      value: workerSecurityGroup.securityGroupId,
    });
    new CfnOutput(this, "WebhookFunctionName", { value: webhookFn.functionName });
    new CfnOutput(this, "DispatcherFunctionName", { value: dispatcherFn.functionName });
    new CfnOutput(this, "DlqConsumerFunctionName", { value: dlqConsumerFn.functionName });
    new CfnOutput(this, "LlmProviderModel", {
      value: `${props.llmConfig.provider}/${props.llmConfig.model}`,
    });
  }
}
