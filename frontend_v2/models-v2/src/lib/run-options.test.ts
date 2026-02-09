import { buildRunOptions } from "@/lib/run-options";

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

export function testRunOptionsLatestDedupAndLabels(): void {
  const latestRunId = "20260209_20z";
  const runIds = ["20260209_20z", "20260209_19z"];
  const options = buildRunOptions(runIds, latestRunId);

  assert(options[0]?.label === "Latest (20Z 2/09)", "latest label should include formatted UTC run");
  assert(options[1]?.label === "19Z 2/09", "concrete run label should be formatted");
  assert(!options.some((opt) => opt.value === "20260209_20z"), "latest concrete duplicate should be excluded");
}
