// The component gallery: every design-system component in every state, for review and the
// docs screenshot. Dev build only (see main.tsx); never in production or the navigation.
import { useState, type ReactNode } from "react";

import type { DiscoveryResult } from "../api/types";
import * as Icons from "../components/icons";
import { Button } from "../ds/Button";
import { AppHeader, type Stage } from "../ds/AppHeader";
import { ConfidenceBadge, EvidenceBadge, PriorityBadge, SourceBadge, StatusBadge } from "../ds/Badge";
import { chipClass, choicePillClass } from "../ds/classes";
import { Accordion, Bullets, Disclosure, EmptyState, Hint, Notice, UndoToast } from "../ds/Feedback";
import { Card, Checkbox, FileInput, RadioRow, StatTile, TextInput, Textarea } from "../ds/Fields";
import { PageHeader } from "../ds/PageHeader";
import { ScanContext } from "../ds/scanContext";
import { ConfirmButton } from "../components/ConfirmButton";

const SWATCHES = [
  ["bg-canvas", "canvas #F1F9F8"],
  ["bg-surface", "surface #FFFFFF"],
  ["bg-aqua", "aqua #D4F1EE"],
  ["bg-raised", "raised #E8F6F4"],
  ["bg-lagoon", "lagoon #1BA9A6"],
  ["bg-accent", "accent #0B6B68"],
  ["bg-ink", "ink #0E2B28"],
  ["bg-muted", "muted #4A6664"],
  ["bg-line", "line #CFE7E4"],
  ["bg-line-strong", "line-strong #5A8681"],
  ["bg-sev-high", "sev-high #B42318"],
  ["bg-sev-medium", "sev-medium #B54708"],
  ["bg-sev-low", "sev-low #475467"],
  ["bg-sev-info", "sev-info #3C5A72"],
  ["bg-notice", "notice #FEF6E6"],
  ["bg-error-tint", "error tint #FDECEB"],
] as const;

const SAMPLE = {
  started_at: "2026-11-03T05:23:39Z",
  finished_at: "2026-11-03T05:24:49Z",
  mode: "full",
  room_network: "Example-Home",
  network: { cidr: "192.0.2.0/24" },
} as unknown as DiscoveryResult;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`g-${title}`} className="space-y-1.5">
      <h2 id={`g-${title}`} className="text-lg">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-1">{children}</div>;
}

export function Gallery() {
  const [radio, setRadio] = useState("b");
  const [box, setBox] = useState(true);
  const [stage, setStage] = useState<Stage>("results");
  return (
    <>
      <AppHeader
        stage={stage}
        current={stage === "results" ? "handover" : null}
        onNavigate={() => {}}
        hasResults={stage !== "start"}
        baselineSaved={false}
        openTasks={2}
        onNewCheck={() => {}}
        onSaveBaseline={async () => {}}
      />
      <main className="mx-auto max-w-content space-y-4 px-2 py-3 sm:px-3">
        <ScanContext.Provider value={SAMPLE}>
          <PageHeader focus={false} intro="Every design-system component in every state. Dev build only.">
            Component gallery
          </PageHeader>
        </ScanContext.Provider>

        <Section title="Header stages">
          <Row>
            {(["start", "scanning", "results"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={stage === s} onClick={() => setStage(s)} className={`rounded-full px-1.5 py-0.5 text-sm font-semibold ${chipClass(stage === s)}`}>
                {s}
              </button>
            ))}
          </Row>
        </Section>

        <Section title="Colour tokens">
          <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
            {SWATCHES.map(([cls, name]) => (
              <div key={name} className="flex items-center gap-1 text-sm">
                <span aria-hidden="true" className={`size-4 shrink-0 rounded-control border border-line ${cls}`} />
                {name}
              </div>
            ))}
          </div>
        </Section>

        <Section title="Type scale">
          <p className="text-2xl font-semibold">Page title, 36 / 1.15</p>
          <p className="text-lg font-semibold">Section heading, 20 / 1.4</p>
          <p className="text-card font-semibold">Card title, 18 / 1.4</p>
          <p className="max-w-measure">Body, 16 / 1.6. Lines stay at about 70 characters, so long paragraphs are easy to read on a wide screen.</p>
          <p className="text-sm text-muted">Helper, 14 / 1.5</p>
          <p className="text-sm font-semibold">Label, 14 / 1.5, semibold</p>
        </Section>

        <Section title="Buttons">
          <Row>
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="text">Text</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="destructive-confirm">Destructive, confirm</Button>
          </Row>
          <Row>
            <Button variant="primary" unavailable aria-describedby="g-why">
              Unavailable
            </Button>
            <Button variant="primary" loading>
              Loading
            </Button>
            <Button variant="primary" size="sm">
              Small
            </Button>
            <Button variant="secondary" size="sm" icon={<Icons.NewCheckIcon />}>
              With icon
            </Button>
          </Row>
          <Hint id="g-why">Unavailable buttons stay focusable and say why, like this hint.</Hint>
          <ConfirmButton label="Delete (asks first)" question="Delete this? It can't be recovered." yes="Yes, delete it" no="Keep it" destructive onConfirm={() => {}} />
        </Section>

        <Section title="Badges and chips">
          <Row>
            {(["High", "Medium", "Low", "Info"] as const).map((l) => (
              <PriorityBadge key={l} level={l} />
            ))}
          </Row>
          <Row>
            {(["Likely", "Possible", "Unclear"] as const).map((b) => (
              <ConfidenceBadge key={b} band={b} />
            ))}
          </Row>
          <Row>
            {(["todo", "asked", "resolved"] as const).map((s) => (
              <StatusBadge key={s} status={s} />
            ))}
            <EvidenceBadge>Host confirmed</EvidenceBadge>
            <EvidenceBadge>Observed by RoomCheck</EvidenceBadge>
            <SourceBadge source="network" />
            <SourceBadge source="nearby" />
          </Row>
          <Row>
            <span className={choicePillClass(false)}>Choice</span>
            <span className={choicePillClass(true)}>Choice, selected</span>
          </Row>
        </Section>

        <Section title="Stat tiles">
          <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
            <StatTile label="Static" value={<span className="text-xl font-semibold">3</span>} />
            <StatTile label="Filter" value={<span className="text-xl font-semibold">2</span>} pressed={false} onClick={() => {}} />
            <StatTile label="Filter, selected" value={<span className="text-xl font-semibold">5</span>} pressed onClick={() => {}} />
          </div>
        </Section>

        <Section title="Notices, hints, empty state, Undo">
          <Notice tone="info" title="Info: something worth knowing." />
          <Notice tone="warning" title="Warning: a check couldn't finish.">
            The rest of the check carries on.
          </Notice>
          <Notice tone="error" title="Error: the files don't match." />
          <Hint>A quiet hint with an info icon.</Hint>
          <EmptyState title="Nothing here yet">Run a check to see results.</EmptyState>
          <UndoToast message="Status changed to Asked." onUndo={() => {}} onExpire={() => {}} />
        </Section>

        <Section title="Disclosure and accordion">
          <Disclosure summary="What does this mean?">
            <Bullets items={["A bullet in the shared list style.", "Another one."]} />
          </Disclosure>
          <Accordion summary="An accordion row">Its content, inside a card.</Accordion>
        </Section>

        <Section title="Form controls">
          <Card>
            <fieldset className="space-y-0.5">
              <legend className="font-semibold">Radio rows</legend>
              <RadioRow name="g" value="a" checked={radio === "a"} onChange={() => setRadio("a")} label="Not selected" hint="Its second line." />
              <RadioRow name="g" value="b" checked={radio === "b"} onChange={() => setRadio("b")} label="Selected" hint="A teal edge and an aqua tint." />
            </fieldset>
            <Checkbox label="A checkbox" hint="What it means, as its description." checked={box} onChange={setBox} />
            <div className="mt-1.5 space-y-1.5">
              <TextInput label="Text input" hint="A hint under the label." defaultValue="Room 4B" />
              <TextInput label="Text input with an error" error="Use up to 40 characters." defaultValue="<b>" />
              <Textarea label="Textarea" hint="Saved automatically." rows={2} />
              <FileInput label="File input" hint="The .pdf file RoomCheck made." accept=".pdf" onPick={() => {}} />
            </div>
          </Card>
        </Section>

        <Section title="Icons">
          <Row>
            {[
              ["Check", <Icons.StepIcon key="d" state="done" />],
              ["Running", <Icons.StepIcon key="r" state="running" />],
              ["Info", <Icons.InfoIcon key="i" />],
              ["Problem", <Icons.ProblemIcon key="p" />],
              ["Devices", <Icons.DevicesIcon key="v" />],
              ["Network", <Icons.RouterIcon key="n" />],
              ["Nearby", <Icons.NearbyIcon key="b" />],
              ["Help", <Icons.HelpIcon key="h" />],
              ["Undo", <Icons.UndoIcon key="u" />],
            ].map(([name, icon]) => (
              <span key={name as string} className="inline-flex items-center gap-0.5 text-sm">
                <span className="text-accent">{icon}</span>
                {name}
              </span>
            ))}
          </Row>
        </Section>
      </main>
    </>
  );
}
