import type { ReactNode } from 'react';
import { Group, Paper, Text, ThemeIcon } from '@mantine/core';

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  color?: string;
}

export function StatCard({ label, value, hint, icon, color }: StatCardProps) {
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb={4}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
          {label}
        </Text>
        {icon && (
          <ThemeIcon variant="light" color={color}>
            {icon}
          </ThemeIcon>
        )}
      </Group>
      <Text fz={28} fw={700} className="num">
        {value}
      </Text>
      {hint && (
        <Text size="sm" c="dimmed">
          {hint}
        </Text>
      )}
    </Paper>
  );
}
