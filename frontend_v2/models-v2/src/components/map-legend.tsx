import { useEffect, useRef, useState } from "react";
import { AlertCircle, ChevronDown, ChevronUp } from "lucide-react";

import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

export type LegendEntry = {
  value: number;
  color: string;
};

export type LegendPayload = {
  title: string;
  units?: string;
  kind?: string;
  id?: string;
  entries: LegendEntry[];
  opacity: number;
};

function formatValue(value: number): string {
  if (Number.isInteger(value)) return value.toString();
  if (Math.abs(value) < 0.1) return value.toFixed(2);
  if (Math.abs(value) < 1) return value.toFixed(1);
  return value.toFixed(0);
}

function UnavailablePlaceholder() {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-border/40 bg-[hsl(var(--toolbar))]/95 px-2 py-2 shadow-xl backdrop-blur-md">
      <AlertCircle className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
      <span className="text-xs font-medium text-muted-foreground/80">Legend unavailable</span>
    </div>
  );
}

const RADAR_GROUP_LABELS = ["Rain", "Snow", "Sleet", "Freezing Rain"];

function radarGroupLabel(index: number): string {
  return RADAR_GROUP_LABELS[index] ?? `Type ${index + 1}`;
}

function isRadarPtypeLegend(legend: LegendPayload): boolean {
  const title = legend.title.toLowerCase();
  const kind = legend.kind?.toLowerCase() ?? "";
  const id = legend.id?.toLowerCase() ?? "";
  return (
    kind.includes("radar") ||
    kind.includes("ptype") ||
    id.includes("radar") ||
    id.includes("ptype") ||
    title.includes("p-type") ||
    title.includes("radar_ptype")
  );
}

function groupRadarEntries(entries: LegendEntry[]): LegendEntry[][] {
  const groups: LegendEntry[][] = [];
  let current: LegendEntry[] = [];

  for (const entry of entries) {
    if (entry.value === 0) {
      if (current.length > 0) {
        groups.push(current);
        current = [];
      }
      continue;
    }
    current.push(entry);
  }

  if (current.length > 0) {
    groups.push(current);
  }

  return groups.map((group) => group.slice().reverse());
}

type MapLegendProps = {
  legend: LegendPayload | null;
  onOpacityChange: (opacity: number) => void;
};

export function MapLegend({ legend, onOpacityChange }: MapLegendProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [isSmallScreen, setIsSmallScreen] = useState(false);
  const [fadeKey, setFadeKey] = useState(0);
  const prevTitleRef = useRef(legend?.title);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const handler = (query: MediaQueryList | MediaQueryListEvent) => {
      setIsSmallScreen(query.matches);
      if (query.matches) setCollapsed(true);
    };
    handler(mq);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    if (legend?.title !== prevTitleRef.current) {
      setFadeKey((value) => value + 1);
      prevTitleRef.current = legend?.title;
    }
  }, [legend?.title]);

  if (!legend) {
    return (
      <div className={cn("pointer-events-none fixed z-40", isSmallScreen ? "bottom-24 right-4" : "right-4 top-20")}>
        <UnavailablePlaceholder />
      </div>
    );
  }

  const opacityPercent = Math.round(legend.opacity * 100);
  const groupedRadarEntries = isRadarPtypeLegend(legend) ? groupRadarEntries(legend.entries) : [];
  const showGroupedRadar = groupedRadarEntries.length > 0;

  return (
    <div
      className={cn(
        "fixed z-40 flex w-[200px] flex-col overflow-hidden rounded-md border border-border/50 bg-[hsl(var(--toolbar))]/95 shadow-xl backdrop-blur-md transition-all duration-200",
        isSmallScreen ? "bottom-24 right-4" : "right-4 top-20"
      )}
      role="complementary"
      aria-label="Map legend"
    >
      <button
        type="button"
        onClick={() => setCollapsed((value) => !value)}
        className="flex w-full items-center justify-between gap-1.5 border-b border-border/30 px-2 py-1.5 text-left transition-all duration-150 hover:bg-secondary/30 active:bg-secondary/50"
        aria-expanded={!collapsed}
        aria-controls="legend-body"
      >
        <div className="flex min-w-0 flex-col gap-0.5 overflow-hidden">
          <span className="truncate text-xs font-semibold tracking-tight text-foreground">{legend.title}</span>
          {legend.units && (
            <span className="text-[10px] font-medium text-muted-foreground/80">{legend.units}</span>
          )}
        </div>
        {collapsed ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150" />
        ) : (
          <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150" />
        )}
      </button>

      <div
        id="legend-body"
        className={cn("grid transition-[grid-template-rows] duration-200 ease-out", collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]")}
      >
        <div className="overflow-hidden">
          <div key={fadeKey} className="flex flex-col gap-2 px-2 py-2 animate-in fade-in duration-200">
            <div className="max-h-[320px] space-y-px overflow-y-auto scroll-smooth">
              {showGroupedRadar
                ? groupedRadarEntries.map((group, groupIndex) => (
                    <div
                      key={`group-${groupIndex}`}
                      className={cn(groupIndex > 0 ? "mt-2 border-t border-border/20 pt-2" : "")}
                    >
                      <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/85">
                        {radarGroupLabel(groupIndex)}
                      </div>
                      {group.map((entry, index) => (
                        <div
                          key={`${entry.value}-${entry.color}-${groupIndex}-${index}`}
                          className={cn(
                            "flex items-center gap-2 rounded-[2px] px-1 py-1 transition-colors duration-150",
                            index % 2 === 0 ? "bg-secondary/20" : "bg-transparent"
                          )}
                        >
                          <span
                            className="h-3 w-4 shrink-0 rounded-[2px] border border-border/30 shadow-sm"
                            style={{ backgroundColor: entry.color }}
                          />
                          <span className="font-mono text-[11px] font-medium leading-none tabular-nums tracking-tight text-foreground/95">
                            {formatValue(entry.value)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ))
                : legend.entries
                    .slice()
                    .reverse()
                    .map((entry, index) => (
                      <div
                        key={`${entry.value}-${entry.color}-${index}`}
                        className={cn(
                          "flex items-center gap-2 rounded-[2px] px-1 py-1 transition-colors duration-150",
                          index % 2 === 0 ? "bg-secondary/20" : "bg-transparent"
                        )}
                      >
                        <span
                          className="h-3 w-4 shrink-0 rounded-[2px] border border-border/30 shadow-sm"
                          style={{ backgroundColor: entry.color }}
                        />
                        <span className="font-mono text-[11px] font-medium leading-none tabular-nums tracking-tight text-foreground/95">
                          {formatValue(entry.value)}
                        </span>
                      </div>
                    ))}
            </div>

            <div className="border-t border-border/30 pt-2">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Opacity
                </span>
                <span className="font-mono text-[10px] font-medium tabular-nums tracking-tight text-foreground/90">
                  {opacityPercent}%
                </span>
              </div>
              <Slider
                value={[opacityPercent]}
                onValueChange={([value]) => onOpacityChange((value ?? 100) / 100)}
                min={0}
                max={100}
                step={1}
                className="w-full transition-opacity duration-150"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
