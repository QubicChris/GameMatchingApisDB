import { Button, Stack, Title } from '@mantine/core';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <Stack align="flex-start" gap="md">
      <Title order={2}>Page not found</Title>
      <Button component={Link} to="/">
        Back to overview
      </Button>
    </Stack>
  );
}
