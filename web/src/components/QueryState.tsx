import type { ReactNode } from 'react';
import { Alert, Button, Center, Loader, Text } from '@mantine/core';

interface QueryStateProps {
  query: { isLoading: boolean; error: unknown; refetch: () => unknown };
  children: ReactNode;
  empty?: boolean;
  emptyText?: string;
}

export function QueryState({ query, children, empty, emptyText }: QueryStateProps) {
  if (query.isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (query.error) {
    const message = query.error instanceof Error ? query.error.message : String(query.error);
    return (
      <Alert color="red" title="Could not load data">
        <Text size="sm" mb="sm">
          {message}
        </Text>
        <Button size="xs" variant="light" color="red" onClick={() => query.refetch()}>
          Retry
        </Button>
      </Alert>
    );
  }
  if (empty) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        {emptyText ?? 'Nothing to show.'}
      </Text>
    );
  }
  return <>{children}</>;
}
