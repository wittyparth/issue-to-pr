// Thin wrapper for constructing an injectable `DynamoDBDocumentClient`.
//
// Tests never touch real AWS: they build their own fake object implementing
// `.send(command)` and route on `command.constructor.name` (see idempotency,
// allowlist, budget tests), so this module's only job is to provide a lazily
// constructed default client for the Lambda runtime.
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

let defaultDocClient: DynamoDBDocumentClient | undefined;

/**
 * Return the shared default `DynamoDBDocumentClient`, constructing it lazily
 * on first use so importing this module has no AWS SDK side effects.
 */
export function getDefaultDocClient(): DynamoDBDocumentClient {
  defaultDocClient ??= DynamoDBDocumentClient.from(new DynamoDBClient({}));
  return defaultDocClient;
}
