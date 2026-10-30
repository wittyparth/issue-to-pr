// Fargate worker launch (M2).
//
// CRITICAL: the container environment overrides carry run metadata only —
// repo full name, issue number, installation id, run id, branch name, event
// kind, and (M7) the *names* of the githubApp/llmProviders SSM parameters.
// The installation token/secret values themselves are never threaded
// through here, logged, or otherwise placed in task environment/overrides —
// the worker resolves them at start via the parameter name using its own
// scoped IAM read (see worker/src/it2pr_worker/secrets.py).
import { RunTaskCommand } from "@aws-sdk/client-ecs";
import type { ECSClient } from "@aws-sdk/client-ecs";
import {
  getEcsCluster,
  getEcsContainerName,
  getEcsSecurityGroups,
  getEcsSubnets,
  getEcsTaskDefinition,
} from "./config.js";

export interface LaunchWorkerParams {
  repoFullName: string;
  issueNumber: number;
  installationId: number;
  runId: string;
  branch: string;
  kind: string;
}

/** Launch the ephemeral Fargate worker task for a claimed, allowlisted, budgeted run. */
export async function launchWorker(ecsClient: ECSClient, params: LaunchWorkerParams): Promise<void> {
  const environment = [
    { name: "REPO_FULL_NAME", value: params.repoFullName },
    { name: "ISSUE_NUMBER", value: String(params.issueNumber) },
    { name: "INSTALLATION_ID", value: String(params.installationId) },
    { name: "RUN_ID", value: params.runId },
    { name: "BRANCH", value: params.branch },
    { name: "EVENT_KIND", value: params.kind },
  ];

  // Metadata only: pass the parameter names (never the value) so the worker
  // can resolve credentials itself via its scoped SSM read.
  const githubAppParamName = process.env["GITHUB_APP_PARAM_NAME"];
  if (githubAppParamName) {
    environment.push({ name: "GITHUB_APP_PARAM_NAME", value: githubAppParamName });
  }
  const llmProvidersParamName = process.env["LLM_PROVIDERS_PARAM_NAME"];
  if (llmProvidersParamName) {
    environment.push({ name: "LLM_PROVIDERS_PARAM_NAME", value: llmProvidersParamName });
  }

  await ecsClient.send(
    new RunTaskCommand({
      cluster: getEcsCluster(),
      taskDefinition: getEcsTaskDefinition(),
      launchType: "FARGATE",
      networkConfiguration: {
        awsvpcConfiguration: {
          subnets: getEcsSubnets(),
          securityGroups: getEcsSecurityGroups(),
          assignPublicIp: "ENABLED",
        },
      },
      overrides: {
        containerOverrides: [
          {
            name: getEcsContainerName(),
            environment,
          },
        ],
      },
    }),
  );
}
