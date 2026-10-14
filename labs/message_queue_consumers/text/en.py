"""Lab message_queue_consumers, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Message queue consumers"
SUMMARY = "Workers take jobs from a queue. Lose none, do each once, and park the poison."
PARAMS = {"rate": "jobs sent per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "CRASH", "slow": "SLOW", "poison": "POISON", "blip": "BLIP", "calm": "CALM"}
CAUSES = {
    "deploy": "a deploy kills workers without draining them",
    "oom": "a memory leak gets workers OOM-killed",
    "spot": "the spot instances running workers are taken back",
    "node_drain": "Kubernetes drains the nodes the workers run on",
    "migration": "a migration is locking the invoices table",
    "throttling": "the email provider is throttling us",
    "big_exports": "customers are asking for huge exports",
    "cold_cache": "the downstream's cache restarted cold",
    "staging_ids": "a producer deploy sends ids from staging: lookups hang until they time out",
    "schema_change": "a producer renamed a field every job needs",
    "deleted_records": "messages point at records that were deleted",
    "truncated": "a producer bug truncates the payloads",
    "failover": "the downstream database is failing over",
    "dns": "a DNS change makes the downstream unreachable",
    "cert_rotation": "the downstream rotated its certificate badly",
    "conn_reset": "a load balancer resets every connection",
}

STAGES = [
    StageText("Ack on receipt",
              "Challenge: a job that crashes or fails after its ack is lost. Ack after the work.",
              "Stage 1: delete after handle() succeeds; heartbeat while it runs"),
    StageText("Ack after work",
              "Challenge: poison messages fail forever and never leave the queue. Park them in a DLQ.",
              "Stage 2: on failure back off; after MAX_RECEIVES, send to the DLQ"),
    StageText("Retries + DLQ",
              "Solved: no job lost, none done twice at once, and poison waits in the DLQ.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "ack jobs in process()"),
    "lost": GoalText("Lost = 0", "ack after the work"),
    "dups": GoalText("Duplicates ≤ 1%", "heartbeat while working"),
    "age": GoalText("Queue age p99 < 1s", "park poison in the DLQ"),
    "dlq": GoalText("DLQ: poison only", "back off, then park"),
}

LEGEND = {"idle": "idle", "first": "1st delivery", "redelivered": "redelivered", "duplicate": "worked twice",
          "acked": "acked", "lost": "lost", "parked": "parked in DLQ", "limit": "jobs sent", "incident": "incident"}

STRINGS = {
    # incidents
    "crash_start": "worker processes crash mid-job: {cause}",
    "crash_end": "the workers stay up again",
    "slow_start": "makes 10% of jobs take {seconds:.1f} s, over the 2 s timeout: {cause}",
    "slow_end": "the downstream is fast again",
    "poison_start": "{share:.0%} of new messages are poison: {cause}",
    "poison_end": "producers send good messages again",
    "blip_start": "every downstream call fails: {cause}",
    "blip_end": "the downstream answers again",
    "warn_lost": "{n} jobs lost",
    "warn_stuck": "{n} messages are still in the queue",
    # goal values
    "none": "none",
    "parked": "{n}/{of}",
    "good_parked": "{n} good",
    # the panel
    "tile_lost": "Lost",
    "tile_dups": "Dups",
    "tile_age": "Age p99",
    "bar_sent": "Sent",
    "bar_tries": "Worked",
    "bar_out": "Ended",
    "limit": "sent",
    "head_lost": "{n} jobs lost in 10 s",
    "head_dups": "{share:.0%} of jobs worked on twice",
    "head_old": "The oldest message is {seconds:.0f} s old",
    "head_crash": "Workers are crashing mid-job",
    "head_slow": "Slow jobs outlast the visibility timeout",
    "head_poison": "Poison messages keep failing",
    "head_blip": "Every job fails for a moment",
    "head_ok": "Every job done once",
    "stat_done": "done",
    "stat_lost": "lost",
    "stat_queued": "queued",
    "stat_dlq": "DLQ",
    "stat_age": "age p99",
    "title": "Jobs",
    "subtitle": "per second, last 1 s",
    # the pictures
    "state_down": "{n} DOWN",
    "state_slow": "SLOW",
    "state_poison": "POISON",
    "state_blip": "FAILING",
    "state_old": "OLD MESSAGES",
    "pic_state": "queue → workers → DLQ: {state}",
    "note": "Dots are a sample of jobs, slowed down (cosmetic).",
    # errors in your code
    "stuck": "a process() call has been running for over {seconds:.0f} s: start the heartbeat as a task, "
             "and does it ever return?",
}

LESSON = Lesson(
    title="Message queue consumers",
    one_liner="A queue hands each job to one worker for a while. When to ack, how to keep it, and when to give up.",
    learn=(
        "A queue like SQS does not give a message away: it lends it. A received message is hidden from other "
        "workers for its visibility timeout; if it is not deleted (acked) by then, the queue hands it to "
        "another worker. That is what makes it at-least-once: nothing is lost, but anything can come twice.",
        "Ack on receipt turns that into at-most-once: a worker that crashes mid-job (a deploy, an OOM kill), "
        "or a job that fails, loses the job for good. Ack after the work instead: a crash or a failure leaves "
        "the message in the queue, and it comes back.",
        "But a job that takes longer than the visibility timeout comes back while the first worker is still on "
        "it: two workers do the same job. Keep a heartbeat: extend the visibility every few seconds while you "
        "work, and stop when you are done or dead. Make the job idempotent anyway: duplicates still happen.",
        "Some messages never succeed (a bad producer deploy, a missing record). Retried forever they eat "
        "workers and the oldest-message age grows without end. Retry a few times with backoff (a short blip "
        "then passes), and after that move the message to a dead-letter queue for a human to look at.",
    ),
    watch_for=(
        "Ack on receipt: when workers crash or a blip fails every job, jobs are lost (red).",
        "Ack after work: nothing lost, slow jobs not done twice, but poison never leaves the queue: "
        "it is still there minutes later, and the DLQ stays empty.",
        "Retries + DLQ: poison goes to the DLQ after MAX_RECEIVES tries (purple), and a short blip parks nothing.",
    ),
    build=(
        ("SQS: a redrive policy moves a message to the DLQ after maxReceiveCount deliveries",
         "aws sqs set-queue-attributes --queue-url $QUEUE --attributes '{\n"
         "  \"VisibilityTimeout\": \"30\",\n"
         "  \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"'$DLQ_ARN'\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}'"),
        ("boto3: heartbeat while the job runs, delete when it is done",
         "while not job.done():\n"
         "    sqs.change_message_visibility(QueueUrl=url, ReceiptHandle=msg[\"ReceiptHandle\"],\n"
         "                                  VisibilityTimeout=30)\n"
         "    job.wait(timeout=10)\n"
         "sqs.delete_message(QueueUrl=url, ReceiptHandle=msg[\"ReceiptHandle\"])"),
        ("RabbitMQ: manual acks, and a dead-letter exchange for rejected messages",
         "channel.queue_declare(\"jobs\", arguments={\"x-dead-letter-exchange\": \"jobs.dlx\"})\n"
         "channel.basic_consume(\"jobs\", on_message, auto_ack=False)\n"
         "# on success: ch.basic_ack(tag); on poison: ch.basic_nack(tag, requeue=False)"),
    ),
    checklist=(
        "Ack (delete) only after the work is done, never on receipt.",
        "Set the visibility timeout above the usual job time, and heartbeat for the long ones.",
        "Stop the heartbeat when the job ends, fails or the process dies.",
        "Make every job idempotent: at-least-once means some jobs run twice.",
        "Retry failures with exponential backoff and jitter, a bounded number of times.",
        "Send what keeps failing to a dead-letter queue, alarm on it, and have a way to redrive it.",
        "Alarm on the age of the oldest message, not just on the queue length.",
    ),
    refs=(
        Ref("Amazon SQS: Visibility timeout",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html",
            "How a received message is hidden, and when it comes back."),
        Ref("Amazon SQS: ChangeMessageVisibility",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html",
            "The call behind a heartbeat (and behind a retry delay)."),
        Ref("Amazon SQS: Dead-letter queues",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html",
            "maxReceiveCount, the redrive policy, and redriving messages back."),
        Ref("AWS Builders' Library: Timeouts, retries, and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Why retries need backoff, jitter and a limit."),
        Ref("Google Cloud Pub/Sub: Handling message failures",
            "https://cloud.google.com/pubsub/docs/handling-failures",
            "The same ideas in another broker: retry policies and dead-letter topics."),
        Ref("RabbitMQ: Consumer acknowledgements",
            "https://www.rabbitmq.com/docs/confirms",
            "Automatic vs manual acks, and what happens to unacked messages."),
    ),
    try_next=(
        "Do stage 1 in labs/message_queue_consumers/main.py and watch the next crash: nothing turns red.",
        "Remove the heartbeat for a minute and watch a slow downstream: jobs are worked on twice.",
        "Do stage 2 and watch the poison go to the DLQ (purple), while a short blip parks nothing.",
    ),
)
