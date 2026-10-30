// Thin wrapper over @aws-sdk/client-sqs for enqueuing trigger work items.
import { SendMessageCommand, SQSClient } from "@aws-sdk/client-sqs";
import type { SQSClientConfig } from "@aws-sdk/client-sqs";

export interface SqsSender {
  send(deliveryId: string, message: unknown): Promise<void>;
}

let defaultClient: SQSClient | undefined;

function getDefaultClient(): SQSClient {
  defaultClient ??= new SQSClient({} satisfies SQSClientConfig);
  return defaultClient;
}

/**
 * Create an `SqsSender` that publishes JSON messages to `queueUrl`, tagging
 * each message with the originating webhook delivery id as a message
 * attribute so downstream consumers/dead-letter tooling can trace it back.
 */
export function createSqsSender(queueUrl: string, client: SQSClient = getDefaultClient()): SqsSender {
  return {
    async send(deliveryId: string, message: unknown): Promise<void> {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(message),
          MessageAttributes: {
            DeliveryId: {
              DataType: "String",
              StringValue: deliveryId,
            },
          },
        }),
      );
    },
  };
}
