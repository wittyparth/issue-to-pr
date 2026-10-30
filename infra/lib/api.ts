import { CfnOutput } from "aws-cdk-lib";
import { HttpApi, HttpMethod } from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import type { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";
import type { Construct } from "constructs";

/**
 * HTTP API Gateway front door for the control plane (M6): a single
 * `POST /webhook` route integrated with the webhook Lambda. No auth at the
 * API Gateway layer — the webhook handler itself verifies the GitHub HMAC
 * signature on every request.
 */
export interface ApiResources {
  readonly httpApi: HttpApi;
}

export function createApi(scope: Construct, webhookFn: NodejsFunction): ApiResources {
  const httpApi = new HttpApi(scope, "HttpApi", {
    apiName: "it2pr-api",
    description: "GitHub Issue-to-PR webhook receiver",
  });

  httpApi.addRoutes({
    path: "/webhook",
    methods: [HttpMethod.POST],
    integration: new HttpLambdaIntegration("WebhookIntegration", webhookFn),
  });

  new CfnOutput(scope, "HttpApiUrl", { value: httpApi.apiEndpoint });

  return { httpApi };
}
