#!/usr/bin/env node
import { App } from "aws-cdk-lib";
import { It2prStack } from "../lib/it2pr-stack.js";

const app = new App();

const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.CDK_DEFAULT_REGION ?? "us-east-1";

// Default to DeepSeek via OpenRouter (cheap, capable) for initial testing.
// Override at deploy time: `cdk deploy -c llmProvider=... -c llmModel=...`
const llmProvider = app.node.tryGetContext("llmProvider") ?? "openrouter";
const llmModel = app.node.tryGetContext("llmModel") ?? "deepseek/deepseek-chat";

new It2prStack(app, "It2prStack", {
  env: account ? { account, region } : { region },
  description: "GitHub Issue-to-PR autonomous agent — control plane",
  llmConfig: { provider: llmProvider, model: llmModel },
});

app.synth();
