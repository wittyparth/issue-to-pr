// Invite-only installation allowlist check (M2).
//
// An installation is allowed to trigger runs only if it has an item in the
// `installations` table (PK `install_id`) and that item's `allowlisted`
// field is not explicitly `false`. A missing item is treated as not
// allowlisted (deny by default).
import { GetCommand } from "@aws-sdk/lib-dynamodb";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { getInstallationsTable } from "./config.js";

/** Check whether `installationId` is allowlisted to trigger runs. */
export async function isAllowlisted(
  docClient: DynamoDBDocumentClient,
  installationId: number,
): Promise<boolean> {
  const result = await docClient.send(
    new GetCommand({
      TableName: getInstallationsTable(),
      // The `installations` table's `install_id` partition key is STRING
      // (see infra/lib/data.ts); coerce the numeric webhook installation id
      // to match, otherwise a real DynamoDB table rejects the GetCommand
      // with a ValidationException (key type mismatch).
      Key: { install_id: String(installationId) },
    }),
  );

  const item = result.Item;
  if (!item) return false;
  return item["allowlisted"] !== false;
}
