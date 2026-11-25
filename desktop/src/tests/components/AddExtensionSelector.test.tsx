import { beforeAll, afterEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { randomFillSync } from 'crypto';
import { clearMocks } from '@tauri-apps/api/mocks';
import { AddExtensionSelector, PythonVersionSelector } from '../../components/AddExtensionSelector';

// Mock the global fetch API
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock data for extensions
const mockExtensionsData = {
  providers: [
    { packageName: 'provider1', reprName: 'Provider One', description: 'Desc 1', category: 'provider' },
    { packageName: 'provider2', reprName: 'Provider Two', description: 'Desc 2', category: 'provider' },
  ],
  routers: [
    { packageName: 'router1', reprName: 'Router One', description: 'Desc A', category: 'router' },
  ],
  obbjects: [
    { packageName: 'obbject1', reprName: 'OBBject One', description: 'Desc X', category: 'other-openbb' },
  ],
};

beforeAll(() => {
  Object.defineProperty(window, 'crypto', {
    value: {
      getRandomValues: (buffer: Uint8Array | Uint16Array | Uint32Array) => {
        return randomFillSync(buffer);
      },
    },
  });
});

// Clear mocks after each test to ensure test isolation
afterEach(() => {
  clearMocks();
  vi.clearAllMocks(); // Clear fetch mock calls
});

test('PythonVersionSelector renders and handles version selection', () => {
  const onSelectVersion = vi.fn();

  render(<PythonVersionSelector onSelectVersion={onSelectVersion} />);

  const python311Radio = screen.getByLabelText(/3.11/i);
  fireEvent.click(python311Radio);

  expect(onSelectVersion).toHaveBeenCalledWith('3.11');
  expect(python311Radio).toBeChecked();

  // The onNext prop and the next button are not part of the component, so we remove these assertions.
});

test('AddExtensionSelector displays loading state initially', () => {
  mockFetch.mockImplementation(() =>
    new Promise(() => {}) // Never resolve to keep it in loading state
  );
  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });
  expect(screen.getByText(/Loading extensions.../i)).toBeInTheDocument();
});

test('AddExtensionSelector fetches and displays extensions', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  // Check if extensions are displayed in their respective categories
  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));
  expect(screen.getByText((content) => content.includes('provider1'))).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes('provider2'))).toBeInTheDocument();

  fireEvent.click(screen.getByRole('tab', { name: /Routers/i }));
  expect(screen.getByText((content) => content.includes('router1'))).toBeInTheDocument();

  fireEvent.click(screen.getByRole('tab', { name: /Others/i }));
  expect(screen.getByText((content) => content.includes('obbject1'))).toBeInTheDocument();
});

test('AddExtensionSelector handles search query', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  // Switch to a tab where search input is visible
  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));

  const searchInput = screen.getByPlaceholderText(/Search extensions.../i);
  fireEvent.change(searchInput, { target: { value: 'provider one' } });

  // Should only show 'provider1'
  expect(screen.getByText((content) => content.includes('provider1'))).toBeInTheDocument();
  expect(screen.queryByText((content) => content.includes('provider2'))).not.toBeInTheDocument();

  fireEvent.change(searchInput, { target: { value: 'nonexistent' } });
  expect(screen.getByText(/No extensions in this category match the search./i)).toBeInTheDocument();
});

test('AddExtensionSelector allows selecting and deselecting extensions', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));

  const provider1Checkbox = screen.getByLabelText(/provider1/i);
  fireEvent.click(provider1Checkbox);
  expect(provider1Checkbox).toBeChecked();

  const summaryText = screen.getByText((content) => content.includes('0 Conda + 0 PyPI + 1 OpenBB extensions selected'));
  expect(summaryText).toBeInTheDocument();

  fireEvent.click(provider1Checkbox);
  expect(provider1Checkbox).not.toBeChecked();
  expect(screen.getByText((content) => content.includes('0 Conda + 0 PyPI + 0 OpenBB extensions selected'))).toBeInTheDocument();
});

test('AddExtensionSelector handles custom PyPI packages', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /PyPI Packages/i }));

  const customPackageInput = screen.getByPlaceholderText(/PyPI Package Name/i);
  const addButton = screen.getByRole('button', { name: /Add/i });

  fireEvent.change(customPackageInput, { target: { value: 'my-custom-package' } });
  fireEvent.click(addButton);

  expect(screen.getByText(/my-custom-package/i)).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes('0 Conda + 1 PyPI + 0 OpenBB extensions selected'))).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText(/Remove my-custom-package/i));
  expect(screen.queryByText(/my-custom-package/i)).not.toBeInTheDocument();
  expect(screen.getByText((content) => content.includes('0 Conda + 0 PyPI + 0 OpenBB extensions selected'))).toBeInTheDocument();
});

test('AddExtensionSelector handles custom Conda packages', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /Conda Packages/i }));

  const condaChannelInput = screen.getByLabelText(/Channel/i);
  fireEvent.change(condaChannelInput, { target: { value: 'my-channel' } });
  expect(condaChannelInput).toHaveValue('my-channel');

  const condaPackageInput = screen.getByPlaceholderText(/Conda Package Name/i);
  const addButton = screen.getByRole('button', { name: /Add/i });

  fireEvent.change(condaPackageInput, { target: { value: 'my-conda-package' } });
  fireEvent.click(addButton);

  expect(screen.getByText(/my-conda-package/i)).toBeInTheDocument();
  expect(screen.getByText((content) => content.includes('1 Conda + 0 PyPI + 0 OpenBB extensions selected'))).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText(/Remove my-channel:my-conda-package/i));
  expect(screen.queryByText(/my-conda-package/i)).not.toBeInTheDocument();
  expect(screen.getByText((content) => content.includes('0 Conda + 0 PyPI + 0 OpenBB extensions selected'))).toBeInTheDocument();
});

test('AddExtensionSelector calls onInstallExtensions with correct data', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  const onInstallExtensions = vi.fn();
  act(() => {
    render(<AddExtensionSelector onInstallExtensions={onInstallExtensions} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  // Select a provider extension
  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));
  fireEvent.click(screen.getByLabelText(/provider1/i));

  // Add a custom PyPI package
  fireEvent.click(screen.getByRole('tab', { name: /PyPI Packages/i }));
  const customPackageInput = screen.getByPlaceholderText(/PyPI Package Name/i);
  const addCustomButton = screen.getByRole('button', { name: /Add/i });
  fireEvent.change(customPackageInput, { target: { value: 'my-custom-pypi' } });
  fireEvent.click(addCustomButton);

  // Add a conda package
  fireEvent.click(screen.getByRole('tab', { name: /Conda Packages/i }));
  const condaPackageInput = screen.getByPlaceholderText(/Conda Package Name/i);
  const addCondaButton = screen.getByRole('button', { name: /Add/i });
  fireEvent.change(condaPackageInput, { target: { value: 'my-conda-pkg' } });
  fireEvent.click(addCondaButton);

  const installButton = screen.getByRole('button', { name: /Install/i });
  fireEvent.click(installButton);

  await waitFor(() => {
    expect(onInstallExtensions).toHaveBeenCalledTimes(1);
    expect(onInstallExtensions).toHaveBeenCalledWith([
      'provider1',
      'my-custom-pypi',
      'conda:conda-forge:my-conda-pkg', // Default channel
    ]);
  });
});

test('AddExtensionSelector filters out already installed packages', async () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('provider.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.providers) });
    }
    if (url.includes('router.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.routers) });
    }
    if (url.includes('obbject.json')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExtensionsData.obbjects) });
    }
    return Promise.reject(new Error('unknown url'));
  });

  const installed = new Set(['provider1']); // Simulate provider1 already installed
  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} installedPackages={installed} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('tab', { name: /Data Providers/i }));
  expect(screen.queryByText((content) => content.includes('provider1'))).not.toBeInTheDocument(); // Should be filtered out
  expect(screen.getByText((content) => content.includes('provider2'))).toBeInTheDocument(); // Should still be there
});

test('AddExtensionSelector displays error message on fetch failure', async () => {
  mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')));

  act(() => {
    render(<AddExtensionSelector onInstallExtensions={vi.fn()} />);
  });

  await waitFor(() => {
    expect(screen.queryByText(/Loading extensions.../i)).not.toBeInTheDocument();
  });

  expect(screen.getByText(/Failed to load extensions. Please try again or continue without extensions./i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Dismiss/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /Dismiss/i }));
  expect(screen.queryByText(/Failed to load extensions./i)).not.toBeInTheDocument();
});
