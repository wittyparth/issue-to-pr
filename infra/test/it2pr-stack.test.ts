import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { describe, expect, it } from "vitest";
import { It2prStack } from "../lib/it2pr-stack.js";

function synth(id: string): Template {
  const app = new App();
  const stack = new It2prStack(app, id, {
    env: { region: "us-east-1" },
    llmConfig: { provider: "openrouter", model: "deepseek/deepseek-chat" },
  });
  return Template.fromStack(stack);
}

describe("It2prStack", () => {
  it("synthesizes without error", () => {
    const template = synth("TestStack");
    expect(template.toJSON()).toBeTypeOf("object");
  });

  // Enforced from M2.5 onward: the cost model forbids NAT gateways entirely.
  it("provisions zero NAT gateways", () => {
    const template = synth("NoNatStack");
    template.resourceCountIs("AWS::EC2::NatGateway", 0);
  });

  it("provisions public subnets with auto-assigned public IPs", () => {
    const template = synth("PublicSubnetStack");
    template.hasResourceProperties(
      "AWS::EC2::Subnet",
      Match.objectLike({ MapPublicIpOnLaunch: true }),
    );
  });

  it("budgets and runs tables have a TTL on expiresAt", () => {
    const template = synth("TtlStack");
    const tables = template.findResources(
      "AWS::DynamoDB::Table",
      Match.objectLike({
        Properties: Match.objectLike({
          TimeToLiveSpecification: { AttributeName: "expiresAt", Enabled: true },
        }),
      }),
    );
    expect(Object.keys(tables)).toHaveLength(2);
  });

  it("work queue has a redrive policy pointing at a DLQ", () => {
    const template = synth("DlqStack");
    template.hasResourceProperties(
      "AWS::SQS::Queue",
      Match.objectLike({ RedrivePolicy: Match.anyValue() }),
    );
  });

  it("ecs:RunTask is never granted on a wildcard resource", () => {
    const template = synth("LeastPrivStack");
    const policies = template.findResources("AWS::IAM::Policy");

    let sawRunTask = false;
    for (const policy of Object.values(policies)) {
      const policyDocument = (policy as { Properties: { PolicyDocument: { Statement: unknown } } })
        .Properties.PolicyDocument;
      const statements = Array.isArray(policyDocument.Statement)
        ? policyDocument.Statement
        : [policyDocument.Statement];

      for (const statement of statements as Array<{ Action?: unknown; Resource?: unknown }>) {
        const actions = Array.isArray(statement.Action)
          ? statement.Action
          : statement.Action
            ? [statement.Action]
            : [];
        if (!actions.includes("ecs:RunTask")) continue;

        sawRunTask = true;
        const resources = Array.isArray(statement.Resource)
          ? statement.Resource
          : [statement.Resource];
        expect(resources).not.toContain("*");
      }
    }

    expect(sawRunTask).toBe(true);
  });

  it("provisions the worker ECR repository", () => {
    const template = synth("EcrStack");
    template.resourceCountIs("AWS::ECR::Repository", 1);
  });

  // M6: Lambda functions + API Gateway + event sources + DLQ alarm.
  it("provisions an HTTP API with a POST /webhook route", () => {
    const template = synth("ApiStack");
    template.resourceCountIs("AWS::ApiGatewayV2::Api", 1);
    template.hasResourceProperties(
      "AWS::ApiGatewayV2::Route",
      Match.objectLike({ RouteKey: "POST /webhook" }),
    );
  });

  it("provisions the webhook, dispatcher, and DLQ consumer Lambda functions on nodejs22.x", () => {
    const template = synth("FunctionsStack");
    const functions = template.findResources(
      "AWS::Lambda::Function",
      Match.objectLike({
        Properties: Match.objectLike({ Runtime: "nodejs22.x" }),
      }),
    );
    expect(Object.keys(functions).length).toBeGreaterThanOrEqual(3);
  });

  it("wires the work queue to the dispatcher and the DLQ to the consumer via event source mappings", () => {
    const template = synth("EventSourceStack");
    const mappings = template.findResources("AWS::Lambda::EventSourceMapping");
    expect(Object.keys(mappings)).toHaveLength(2);
  });

  it("alarms on the DLQ ApproximateNumberOfMessagesVisible metric", () => {
    const template = synth("DlqAlarmStack");
    template.hasResourceProperties(
      "AWS::CloudWatch::Alarm",
      Match.objectLike({
        MetricName: "ApproximateNumberOfMessagesVisible",
        ComparisonOperator: "GreaterThanThreshold",
        Threshold: 0,
      }),
    );
  });

  // Regression: the webhook function's GH_WEBHOOK_SECRET_ARN must reference
  // a dedicated webhook-signing secret, never the githubAppSecret (which
  // holds the {appId, privateKeyPem} JSON blob) — otherwise HMAC
  // verification always fails and every webhook delivery 401s.
  it("wires the webhook function's GH_WEBHOOK_SECRET_ARN to a secret distinct from the github-app secret", () => {
    const template = synth("WebhookSecretStack");

    const secrets = template.findResources("AWS::SecretsManager::Secret");
    const githubAppSecretLogicalIds = Object.entries(secrets)
      .filter(([, resource]) => {
        const props = (resource as { Properties?: { Name?: string } }).Properties;
        return props?.Name === "it2pr/github-app";
      })
      .map(([id]) => id);
    expect(githubAppSecretLogicalIds).toHaveLength(1);
    const githubAppSecretLogicalId = githubAppSecretLogicalIds[0];

    const functions = template.findResources(
      "AWS::Lambda::Function",
      Match.objectLike({
        Properties: Match.objectLike({ FunctionName: "it2pr-webhook" }),
      }),
    );
    const webhookFnResource = Object.values(functions)[0] as {
      Properties: { Environment: { Variables: Record<string, unknown> } };
    };
    const webhookSecretArnRef = webhookFnResource.Properties.Environment.Variables[
      "GH_WEBHOOK_SECRET_ARN"
    ] as { Ref?: string } | undefined;

    expect(webhookSecretArnRef).toBeDefined();
    expect(webhookSecretArnRef?.Ref).not.toBe(githubAppSecretLogicalId);
  });

  it("bakes LLM_PROVIDER and LLM_MODEL into the worker task definition", () => {
    const template = synth("LlmConfigStack");
    template.hasResourceProperties(
      "AWS::ECS::TaskDefinition",
      Match.objectLike({
        ContainerDefinitions: Match.arrayWith([
          Match.objectLike({
            Environment: Match.arrayWith([
              { Name: "LLM_PROVIDER", Value: "openrouter" },
              { Name: "LLM_MODEL", Value: "deepseek/deepseek-chat" },
            ]),
          }),
        ]),
      }),
    );
  });
});
