import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Checkbox, Code, CopyButton, Group, List, MultiSelect, Paper, Progress, SimpleGrid, Stack,
  Table, Text, Title,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconCopy, IconDownload } from '@tabler/icons-react';
import { api, ApiError } from '../api/client';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { cliCommand, EXPORT_SHEETS, ODDS_SHEETS, presetRange, type RangePreset } from '../lib/exportRanges';
import { formatEta, isActive, JOB_STORAGE_KEY, REVOKE_DELAY_MS, stageLabel } from '../lib/exportProgress';
import { formatNumber } from '../lib/format';

const PRESETS: { label: string; value: RangePreset }[] = [
  { label: 'Latest day', value: 'latest' },
  { label: 'Last 7 days', value: 'last7' },
  { label: 'Last 30 days', value: 'last30' },
];

export function ExportPage() {
  const filters = useQuery({ queryKey: ['filters'], queryFn: api.filters });
  const dates = filters.data?.dates ?? [];
  const newest = dates[0];
  const oldest = dates[dates.length - 1];

  const [range, setRange] = useState<[string | null, string | null]>([null, null]);
  const [countries, setCountries] = useState<string[]>([]);
  const [leagues, setLeagues] = useState<string[]>([]);
  const [umids, setUmids] = useState<string[]>([]);
  const [sheets, setSheets] = useState<string[]>([...EXPORT_SHEETS]);
  const [starting, setStarting] = useState(false);
  const [jobError, setJobError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(() => {
    try { return sessionStorage.getItem(JOB_STORAGE_KEY); } catch { return null; }
  });
  const handledRef = useRef<string | null>(null);

  const rememberJob = (id: string | null) => {
    setJobId(id);
    try {
      if (id) sessionStorage.setItem(JOB_STORAGE_KEY, id);
      else sessionStorage.removeItem(JOB_STORAGE_KEY);
    } catch { /* storage unavailable */ }
  };

  const job = useQuery({
    queryKey: ['export-job', jobId],
    queryFn: () => api.exportJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => (isActive(q.state.data) ? 1000 : false),
    retry: false,
  });
  const jobData = job.data;
  const busy = starting || isActive(jobData) || (!!jobId && job.isPending);

  useEffect(() => {
    if (job.error instanceof ApiError && job.error.status === 404) rememberJob(null);
  }, [job.error]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!jobId || !jobData) return;
    const key = `${jobId}:${jobData.state}`;
    if (jobData.state === 'done') {
      if (handledRef.current === key) return;
      handledRef.current = key;
      void (async () => {
        try {
          const { blob, filename } = await api.downloadExportJob(jobId);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
          notifications.show({ color: 'teal', title: 'Export ready', message: filename });
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            notifications.show({ color: 'yellow', title: 'Export', message: 'This export was already downloaded' });
          } else {
            notifications.show({
              color: 'red', title: 'Export failed', message: err instanceof Error ? err.message : String(err),
            });
          }
        } finally {
          rememberJob(null);
        }
      })();
    } else if (jobData.state === 'error') {
      if (handledRef.current === key) return;
      handledRef.current = key;
      setJobError(jobData.error ?? 'Export failed');
      rememberJob(null);
    } else if (jobData.state === 'cancelled') {
      if (handledRef.current === key) return;
      handledRef.current = key;
      notifications.show({ color: 'gray', title: 'Export', message: 'Export cancelled' });
      rememberJob(null);
    }
  }, [jobId, jobData?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const matchRates = useQuery({ queryKey: ['match-rates'], queryFn: api.matchRates });
  const marketTypes = useQuery({ queryKey: ['market-types'], queryFn: api.marketTypes });

  const leagueOptions = useMemo(() => {
    const names = new Set<string>();
    for (const l of matchRates.data?.leagues ?? []) {
      if (countries.length === 0 || countries.includes(l.country)) names.add(l.league);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [matchRates.data, countries]);

  useEffect(() => {
    setLeagues((cur) => {
      const next = cur.filter((l) => leagueOptions.includes(l));
      return next.length === cur.length ? cur : next;
    });
  }, [leagueOptions]);

  const marketOptions = (marketTypes.data ?? []).map((m) => ({
    value: String(m.umid),
    label: `${m.canonical_name ?? 'Market ' + m.umid} (#${m.umid})`,
  }));

  useEffect(() => {
    if (range[0] == null && range[1] == null && dates.length > 0) {
      setRange(presetRange('last7', dates) ?? [null, null]);
    }
  }, [dates]); // eslint-disable-line react-hooks/exhaustive-deps

  const [from, to] = range;
  const ready = !!from && !!to;
  const noSheets = sheets.length === 0;

  const params = {
    date_from: from as string,
    date_to: to as string,
    include_odds: true,
    countries,
    leagues,
    umids: umids.map(Number),
    sheets: sheets.length === EXPORT_SHEETS.length ? [] : sheets,
  };

  const preview = useQuery({
    queryKey: ['export-preview', params],
    queryFn: () => api.exportPreview(params),
    enabled: ready && !noSheets,
  });
  const p = preview.data;
  const cli = ready
    ? cliCommand(from as string, to as string, { countries, leagues, umids: umids.map(Number), sheets })
    : '';

  const download = async () => {
    if (!from || !to) return;
    setStarting(true);
    setJobError(null);
    try {
      const j = await api.startExport(params);
      rememberJob(j.id);
    } catch (err) {
      notifications.show({
        color: 'red', title: 'Export failed', message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    try {
      await api.cancelExport(jobId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) {
        notifications.show({
          color: 'red', title: 'Cancel failed', message: err instanceof Error ? err.message : String(err),
        });
      }
    }
  };

  return (
    <>
      <PageHeader
        title="Export to Excel"
        description="Download every table for a kickoff date range as one workbook with readable column names."
      />
      <Stack gap="md" maw={760}>
        <Paper withBorder p="lg">
          <Stack gap="sm">
            <DatePickerInput
              type="range"
              label="Kickoff dates (UTC)"
              value={range}
              onChange={(v) => setRange([v[0] as string | null, v[1] as string | null])}
              minDate={oldest}
              maxDate={newest}
              valueFormat="D MMM YYYY"
              w={320}
              disabled={busy}
            />
            <Group gap="xs">
              {PRESETS.map((pr) => (
                <Button
                  key={pr.value} variant="default" size="xs" disabled={busy}
                  onClick={() => {
                    const r = presetRange(pr.value, dates);
                    if (r) setRange(r);
                  }}
                >
                  {pr.label}
                </Button>
              ))}
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">Filters</Title>
          <Stack gap="sm">
            <MultiSelect
              label="Countries" placeholder="All countries"
              data={filters.data?.countries ?? []} value={countries} onChange={setCountries}
              searchable clearable disabled={busy}
            />
            <MultiSelect
              label="Leagues" placeholder="All leagues"
              data={leagueOptions} value={leagues} onChange={setLeagues}
              searchable clearable disabled={busy}
            />
            <MultiSelect
              label="Markets" placeholder="All markets"
              description="Applies to Odds, Exchange Ladder and Sofa Odds"
              data={marketOptions} value={umids} onChange={setUmids}
              searchable clearable disabled={busy}
            />
            <Checkbox.Group label="Sheets" value={sheets} onChange={setSheets}>
              <SimpleGrid cols={{ base: 1, sm: 2 }} mt="xs" spacing="xs">
                {EXPORT_SHEETS.map((name) => (
                  <Checkbox key={name} value={name} label={name} disabled={busy} />
                ))}
              </SimpleGrid>
            </Checkbox.Group>
            <Group gap="xs">
              <Button variant="default" size="xs" disabled={busy} onClick={() => setSheets([...EXPORT_SHEETS])}>
                All
              </Button>
              <Button
                variant="default" size="xs" disabled={busy}
                onClick={() => setSheets(EXPORT_SHEETS.filter((n) => !ODDS_SHEETS.includes(n)))}
              >
                No odds sheets
              </Button>
            </Group>
            {noSheets && <Text c="red" size="sm">Pick at least one sheet.</Text>}
          </Stack>
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">Preview</Title>
          {!ready ? (
            <Text c="dimmed" size="sm">Pick a date range to see what will be exported.</Text>
          ) : (
            <QueryState query={preview}>
              {p && (
                <Stack gap="sm">
                  <Table>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Sheet</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>Rows</Table.Th>
                        <Table.Th />
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {p.sheets.map((s) => (
                        <Table.Tr key={s.name}>
                          <Table.Td>{s.name}</Table.Td>
                          <Table.Td style={{ textAlign: 'right' }} className="num">{formatNumber(s.rows)}</Table.Td>
                          <Table.Td>
                            {p.too_large.includes(s.name) && <Badge color="red">Too large</Badge>}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                  <Text size="xs" c="dimmed">
                    {`Max ${formatNumber(p.max_rows)} rows per sheet. Team Aliases and Market Types always include all rows.`}
                  </Text>
                  {!p.ok && (
                    <Alert color="red" title="Range too large for Excel">
                      Shorten the date range, add filters or leave out odds sheets.
                    </Alert>
                  )}
                </Stack>
              )}
            </QueryState>
          )}
          {jobError && (
            <Alert color="red" title="Export failed" mt="md" withCloseButton onClose={() => setJobError(null)}>
              {jobError}
            </Alert>
          )}
          <Group mt="md">
            <Button
              size="md" leftSection={<IconDownload size={18} />}
              disabled={!p?.ok || noSheets} loading={busy} onClick={download}
            >
              Download Excel
            </Button>
          </Group>
          {isActive(jobData) && jobData ? (
            <Stack gap={4} mt="sm">
              <Group justify="space-between">
                <Text size="sm" fw={500}>{stageLabel(jobData)}</Text>
                <Text size="sm" c="dimmed" className="num">{Math.round(jobData.percent)}%</Text>
              </Group>
              <Progress value={jobData.percent} size="lg" animated striped />
              <Group justify="space-between">
                <Text size="xs" c="dimmed">{formatEta(jobData.eta_seconds)}</Text>
                <Button size="xs" variant="subtle" color="red" onClick={cancel}>Cancel</Button>
              </Group>
            </Stack>
          ) : (
            <Text size="xs" c="dimmed" mt="xs">
              Large exports can take a minute or two. Filters and fewer sheets make them faster.
            </Text>
          )}
        </Paper>

        <Paper withBorder p="lg">
          <Title order={5} mb="sm">What&apos;s in the workbook</Title>
          <List size="sm" spacing={2}>
            <List.Item>Summary</List.Item>
            <List.Item>Games</List.Item>
            <List.Item>Bookmaker Games</List.Item>
            <List.Item>Odds (one column per bookmaker, best price, Sofa closing odds and result)</List.Item>
            <List.Item>Exchange Ladder (back/lay prices &amp; sizes)</List.Item>
            <List.Item>Sofa Odds</List.Item>
            <List.Item>Match Stats (every stat, home/away, per period)</List.Item>
            <List.Item>Incidents</List.Item>
            <List.Item>Match Rates</List.Item>
            <List.Item>Team Aliases</List.Item>
            <List.Item>Market Types</List.Item>
          </List>
        </Paper>

        {ready && (
          <Paper withBorder p="lg">
            <Title order={5} mb="sm">Command line</Title>
            <CopyButton value={cli}>
              {({ copied, copy }) => (
                <Group wrap="nowrap" align="flex-start">
                  <Code block style={{ flex: 1 }}>{cli}</Code>
                  <Button
                    variant="default" size="xs" onClick={copy}
                    leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </Group>
              )}
            </CopyButton>
          </Paper>
        )}
      </Stack>
    </>
  );
}
