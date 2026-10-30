import { aws_ec2 as ec2 } from "aws-cdk-lib";
import type { Construct } from "constructs";

/**
 * Networking foundation for the control plane (M2.5).
 *
 * SCALE-TO-ZERO: public subnets only, zero NAT gateways. Fargate worker tasks
 * are launched by the dispatcher (see app/src/lib/ecs.ts, M6) with
 * `assignPublicIp: ENABLED` in these public subnets so they can reach
 * github.com and LLM providers directly, without paying for a NAT gateway.
 *
 * Only the free S3/DynamoDB gateway endpoints are provisioned. Interface
 * endpoints (ECR, Secrets Manager, CloudWatch Logs) were deliberately left
 * out: they bill per-AZ-hour (~$55-60/month for 4 endpoints x 2 AZs)
 * regardless of usage, and the worker already has public egress to reach
 * github.com/LLM providers, so it can reach those AWS services over the
 * public internet at no extra fixed cost.
 */
export interface NetworkResources {
  readonly vpc: ec2.IVpc;
  readonly workerSecurityGroup: ec2.SecurityGroup;
}

export function createNetwork(scope: Construct): NetworkResources {
  // aws-cdk-lib's concrete `Vpc` is not structurally assignable to `IVpc`
  // under `exactOptionalPropertyTypes` (its `vpnGatewayId` getter returns
  // `string | undefined` where `IVpc` declares an optional `string`). This
  // is a known aws-cdk-lib typing gap, not a design choice; cast once here
  // so every downstream consumer works against the (correctly typed) `IVpc`
  // interface, which is all that's needed (addGatewayEndpoint,
  // addInterfaceEndpoint, publicSubnets, etc.).
  const vpc = new ec2.Vpc(scope, "Vpc", {
    maxAzs: 2,
    natGateways: 0,
    subnetConfiguration: [
      {
        name: "public",
        subnetType: ec2.SubnetType.PUBLIC,
        cidrMask: 24,
      },
    ],
  }) as unknown as ec2.IVpc;

  // Egress-only security group for the Fargate worker: no inbound rules at
  // all (the worker never accepts connections); default egress (allow-all)
  // is required to reach github.com, LLM provider APIs, and AWS services.
  const workerSecurityGroup = new ec2.SecurityGroup(scope, "WorkerSecurityGroup", {
    vpc,
    description: "Issue-to-PR Fargate worker: no inbound, egress to GitHub/LLM providers/AWS",
    allowAllOutbound: true,
  });

  // Free gateway endpoints.
  vpc.addGatewayEndpoint("S3Endpoint", {
    service: ec2.GatewayVpcEndpointAwsService.S3,
  });
  vpc.addGatewayEndpoint("DynamoDbEndpoint", {
    service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
  });

  return { vpc, workerSecurityGroup };
}
