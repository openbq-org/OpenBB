import { Button, Tooltip } from "@openbb/ui-pro";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import CustomIcon from "./Icon";

// Define types
interface Extension {
  id: string;
  name: string;
  description: string;
  category: string;
  credentials?: string[];
  instructions?: string | null;
}

interface ExtensionCategory {
  id: string;
  name: string;
  description: string;
}

const categories: ExtensionCategory[] = [
  {
    id: "conda",
    name: "Conda Packages",
    description: "Specify Conda packages to install in the environment, optionally with a channel (e.g., conda-forge, <channel-name>) and version specifiers.",
  },
  {
    id: "extras",
    name: "PyPI Packages",
    description: "Packages from PyPI to be installed (pip) in the environment. Use version specifiers as needed (e.g., package==1.2.3 or package>=1.2.3).",
  },
  {
    id: "provider",
    name: "Data Providers",
    description: "Data providers supplying data through the OpenBB provider interface.",
  },
  {
    id: "router",
    name: "Routers",
    description: "API paths and endpoints implementing the OpenBB command interface.",
  },
  {
    id: "other-openbb",
    name: "Others",
    description: "Additional OpenBB extensions, including OBBject extensions, that enhance the functionality of the OpenBB platform.",
  },
];

// Python Version Selector Component
export const PythonVersionSelector = ({
  onSelectVersion,
}: {
  onSelectVersion: (version: string) => void;
}) => {
  const [selectedVersion, setSelectedVersion] = useState<string>("3.12");

  const handleChange = (version: string) => {
    setSelectedVersion(version);
    onSelectVersion(version);
  };

  return (
		<div className="w-full" data-testid="python-version-selector">
			<div className="flex flex-row gap-8 pr-20">
        {["3.11", "3.12", "3.13", "3.14"].map((version) => (
          <label
            key={version}
            className="flex items-center gap-2 cursor-pointer body-xs-regular text-theme-primary"
          >
            <input
              type="radio"
              name="python-version"
              value={version}
              checked={selectedVersion === version}
              onChange={() => handleChange(version)}
              className="sr-only"
            />
            <span
              className={`relative flex items-center justify-center h-5 w-5 rounded-full border-2 ${
                selectedVersion === version
                  ? "border-theme-radio"
                  : "border-theme"
              }`}
            >
              {selectedVersion === version && (
                <span className="h-1.5 w-1.5 rounded-full bg-theme-neutral" />
              )}
            </span>
						<span className={`body-md-regular ${selectedVersion === version ? "text-theme-neutral" : "text-theme-secondary"}`}>{version}</span>
          </label>
        ))}
      </div>
    </div>
  );
};

// Move hasMatchingExtensions outside the component
const hasMatchingExtensions = (extensions: Extension[], categoryId: string, query: string, installedPackages: Set<string>): boolean => {
  if (!query.trim()) return true; // Always show all tabs when no search
  let categoryExtensions = extensions.filter((ext) => ext.category === categoryId);

  // Filter out already installed packages for provider, router, and other-openbb categories
  if (categoryId === "provider" || categoryId === "router" || categoryId === "other-openbb") {
    categoryExtensions = categoryExtensions.filter(
      (ext) => !installedPackages.has(ext.id.toLowerCase())
    );
  }

  const queryLower = query.toLowerCase();
  return categoryExtensions.some(
    (ext) =>
      ext.id.toLowerCase().includes(queryLower) ||
      ext.name.toLowerCase().includes(queryLower) ||
      ext.description.toLowerCase().includes(queryLower)
  );
};

// ExtensionSelector Component
export const AddExtensionSelector = ({
  onInstallExtensions,
  installedPackages = new Set(),
  onCancel,
}: {
  onInstallExtensions: (extensionIds: string[]) => void;
  installedPackages?: Set<string>;
  onCancel?: () => void;
}) => {
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategoryTab, setActiveCategoryTab] = useState(categories[0].id);
  const [localSearchQuery, setLocalSearchQuery] = useState("");

  // Track selected extensions - start with an empty array for no pre-selection
  const [selectedExtensions, setSelectedExtensions] = useState<string[]>([]);

  // Track custom packages
  const [customPackage, setCustomPackage] = useState("");
  const [customPackages, setCustomPackages] = useState<string[]>([]);

  // Track conda packages
  const [condaPackage, setCondaPackage] = useState("");
  const [condaPackages, setCondaPackages] = useState<string[]>([]);
  const [condaChannel, setCondaChannel] = useState("conda-forge");

  // Track installation state
  const [isInstalling, setIsInstalling] = useState(false);

  const extrasExtensions = [
    {
      id: "openbb-mcp-server",
      name: "OpenBB MCP Server",
      description: "Convert OpenBB routes, endpoints, and FastAPI instances to run over the Model Context Protocol (MCP).",
      category: "other-openbb",
      credentials: [],
    },
    {
      id: "pywry",
      name: "PyWry",
      description: "PyWry is a Python wrapper of the Tauri Window builder.",
      category: "other-openbb",
      credentials: [],
    },
    {
      id: "openbb-cli",
      name: "OpenBB CLI",
      description: "Command line interface for OpenBB",
      category: "other-openbb",
      credentials: [],
    },
  ];

  // Update the getFilteredExtensions function to use the new hasMatchingExtensions
  const getFilteredExtensions = (categoryId: string) => {
    let categoryExtensions = extensions.filter(
      (ext) => ext.category === categoryId,
    );

    // Filter out already installed packages for provider, router, and other-openbb categories
    if (categoryId === "provider" || categoryId === "router" || categoryId === "other-openbb") {
      categoryExtensions = categoryExtensions.filter(
        (ext) => !installedPackages.has(ext.id.toLowerCase())
      );
    }

    if (!localSearchQuery.trim()) {
      return categoryExtensions;
    }

    const query = localSearchQuery.toLowerCase();
    return categoryExtensions.filter(
      (ext) =>
        ext.id.toLowerCase().includes(query) ||
        ext.name.toLowerCase().includes(query) ||
        ext.description.toLowerCase().includes(query),
    );
  };



  // Add a conda package
  const addCondaPackage = () => {
    if (!condaPackage.trim() || !condaChannel.trim()) return;

    const newPackage = `${condaChannel.trim()}:${condaPackage.trim()}`;
    // Avoid duplicates
    if (!condaPackages.includes(newPackage)) {
      setCondaPackages((prev) => [...prev, newPackage]);
    }

    setCondaPackage("");
  };

  // Add a custom package
  const addCustomPackage = () => {
    if (!customPackage.trim()) return;

    // Avoid duplicates
    if (!customPackages.includes(customPackage.trim())) {
      setCustomPackages((prev) => [...prev, customPackage.trim()]);
    }

    setCustomPackage("");
  };

  // Remove a conda package
  const removeCondaPackage = (pkg: string) => {
    setCondaPackages((prev) => prev.filter((p) => p !== pkg));
  };

  // Remove a custom package
  const removeCustomPackage = (pkg: string) => {
    setCustomPackages((prev) => prev.filter((p) => p !== pkg));
  };

  // Load extensions from GitHub
  useEffect(() => {
    const fetchExtensions = async () => {
      setLoading(true);
      try {
        const [providersRes, routersRes, obbjectsRes] = await Promise.all([
          fetch(
            "https://raw.githubusercontent.com/OpenBB-finance/OpenBB/main/assets/extensions/provider.json",
          ),
          fetch(
            "https://raw.githubusercontent.com/OpenBB-finance/OpenBB/main/assets/extensions/router.json",
          ),
          fetch(
            "https://raw.githubusercontent.com/OpenBB-finance/OpenBB/main/assets/extensions/obbject.json",
          ),
        ]);

        if (!providersRes.ok || !routersRes.ok || !obbjectsRes.ok) {
          throw new Error("Failed to fetch extensions data");
        }

        const providers = await providersRes.json() as Array<{
          packageName: string;
          reprName?: string;
          description?: string;
          credentials?: string[];
          instructions?: string | null;
        }>;
        const routers = await routersRes.json() as Array<{
          packageName: string;
          reprName?: string;
          description?: string;
          credentials?: string[];
          instructions?: string | null;
        }>;
        const obbjects = await obbjectsRes.json() as Array<{
          packageName: string;
          reprName?: string;
          description?: string;
          credentials?: string[];
          instructions?: string | null;
        }>;

        // Map to common format with categories
        const mappedExtensions: Extension[] = [
          ...providers.map((item) => ({
            id: item.packageName,
            name: item.reprName || item.packageName,
            description: item.description || "No description available",
            category: "provider",
            credentials: item.credentials || [],
            instructions: item.instructions || null,
          })),
          ...routers.map((item) => ({
            id: item.packageName,
            name: item.reprName || item.packageName,
            description: item.description || "No description available",
            category: "router",
            credentials: item.credentials || [],
            instructions: item.instructions || null,
          })),
          ...obbjects.map((item) => ({
            id: item.packageName,
            name: item.reprName || item.packageName,
            description: item.description || "No description available",
            category: "other-openbb",
            credentials: item.credentials || [],
            instructions: item.instructions || null,
          })),
          ...extrasExtensions,
        ];

        setExtensions(mappedExtensions);
      } catch (err) {
        console.error("Error fetching extensions:", err);
        setError(
          "Failed to load extensions. Please try again or continue without extensions.",
        );
      } finally {
        setLoading(false);
      }
    };

    fetchExtensions();
  }, []);

  // Toggle an extension selection
  const toggleExtension = (id: string) => {
    setSelectedExtensions((prev) =>
      prev.includes(id) ? prev.filter((extId) => extId !== id) : [...prev, id],
    );
  };

  // Select all in a category
  const selectCategory = (categoryId: string) => {
    let categoryExtensions = extensions.filter((ext) => ext.category === categoryId);

    // Filter out already installed packages for provider, router, and other-openbb categories
    if (categoryId === "provider" || categoryId === "router" || categoryId === "other-openbb") {
      categoryExtensions = categoryExtensions.filter(
        (ext) => !installedPackages.has(ext.id.toLowerCase())
      );
    }

    const categoryExtensionIds = categoryExtensions.map((ext) => ext.id);

    setSelectedExtensions((prev) => {
      // Remove any existing ones from this category
      const filtered = prev.filter((id) => !categoryExtensionIds.includes(id));
      // Add all from this category
      return [...filtered, ...categoryExtensionIds];
    });
  };

  // Clear all in a category
  const clearCategory = (categoryId: string) => {
    let categoryExtensions = extensions.filter((ext) => ext.category === categoryId);

    // Filter out already installed packages for provider, router, and other-openbb categories
    if (categoryId === "provider" || categoryId === "router" || categoryId === "other-openbb") {
      categoryExtensions = categoryExtensions.filter(
        (ext) => !installedPackages.has(ext.id.toLowerCase())
      );
    }

    const categoryExtensionIds = categoryExtensions.map((ext) => ext.id);

    setSelectedExtensions((prev) =>
      prev.filter((id) => !categoryExtensionIds.includes(id)),
    );
  };

  // Get extensions for a specific category
  const getExtensionsByCategory = (categoryId: string) => {
    let categoryExtensions = extensions.filter((ext) => ext.category === categoryId);

    // Filter out already installed packages for provider, router, and other-openbb categories
    if (categoryId === "provider" || categoryId === "router" || categoryId === "other-openbb") {
      categoryExtensions = categoryExtensions.filter(
        (ext) => !installedPackages.has(ext.id.toLowerCase())
      );
    }

    return categoryExtensions;
  };

  // Count selected extensions in a category
  const countSelectedInCategory = (categoryId: string) => {
    const categoryExtensions = getExtensionsByCategory(categoryId);
    const categoryExtensionIds = categoryExtensions.map((ext) => ext.id);

    return selectedExtensions.filter((id) => categoryExtensionIds.includes(id))
      .length;
  };

  // Handle installation with selected extensions and custom packages
  const handleInstallExtensions = async () => {
    try {
      setIsInstalling(true);
      setError(null);

      const condaPackagesWithChannel = condaPackages.map(
        (pkg) => `conda:${pkg}`,
      );
      const extensionsToInstall = [
        ...selectedExtensions,
        ...customPackages,
        ...condaPackagesWithChannel,
      ];

      console.log("Installing extensions:", extensionsToInstall);

      // Call installation and wait for completion
      onInstallExtensions(extensionsToInstall);

      console.log("Extension installation completed successfully");
    } catch (error) {
      console.error("Installation failed:", error);
      setError(`Installation failed: ${error}`);
    } finally {
      // Always reset the installing state
      setIsInstalling(false);
    }
  };

	const getCheckboxState = (categoryId: string) => {
		const categoryExtensions = getExtensionsByCategory(categoryId);
		const totalCount = categoryExtensions.length;
		const selectedCount = countSelectedInCategory(categoryId);

    if (selectedCount === 0) return 'unchecked';
    if (selectedCount === totalCount) return 'checked';
    return 'indeterminate';
	};

  // Update the useEffect to use the new hasMatchingExtensions
  useEffect(() => {
    // If current active tab has no matches, switch to first available tab
    if (!hasMatchingExtensions(extensions, activeCategoryTab, localSearchQuery, installedPackages)) {
      const firstMatchingCategory = categories.find(category =>
        hasMatchingExtensions(extensions, category.id, localSearchQuery, installedPackages)
      );
      if (firstMatchingCategory) {
        setActiveCategoryTab(firstMatchingCategory.id);
      }
    }
  }, [localSearchQuery, activeCategoryTab, extensions, installedPackages]);

  return (
    <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center px-5">
      <div className="flex flex-col pt-2 px-5 pb-5 bg-theme-secondary rounded-lg border border-theme-modal shadow-lg w-full">
        {loading ? (
          <div className="flex justify-center items-center p-8 text-theme-primary">
            <div className="animate-spin rounded-full h-8 w-8 border-theme-color" />
            <span className="ml-2 body-xs-regular text-theme-primary">Loading extensions...</span>
          </div>
        ) : (
          <>
            <div className="mt-2">
              <div className="flex items-center justify-between mb-2">
                <h2 className="body-lg-bold text-theme-primary mb-1">Install Extensions</h2>
                <Tooltip content="Close" className="tooltip-theme">
                  <Button
                    onClick={onCancel}
                    variant="ghost"
                    size="icon"
                    className="button-ghost"
                    disabled={isInstalling}
                  >
                    <CustomIcon id="close" className="h-6 w-6" />
                  </Button>
                </Tooltip>
              </div>
            </div>
            {/* Tab bar for categories */}
            <div className="flex gap-4 whitespace-nowrap mb-5 border-b-2 border-theme-accent">
              {categories
                .filter(category => hasMatchingExtensions(extensions, category.id, localSearchQuery, installedPackages))
                .map((category, idx) => (
                  <div key={category.id} className="flex items-center">
                    <button
                      type="button"
                      className={`py-1 text-theme transition-colors
                        ${idx === 0 ? 'pl-0' : 'px-0'}
                        ${activeCategoryTab === category.id
                          ? "body-sm-bold border-b tab-border-active text-theme-accent relative -bottom-0.5"
                          : "body-sm-medium text-theme-muted relative -bottom-0.5 "}
                        focus:outline-none
                      `}
                      onClick={() => setActiveCategoryTab(category.id)}
                      aria-selected={activeCategoryTab === category.id}
                      role="tab"
                    >
                      {category.name}
                    </button>
                  </div>
                ))}
            </div>

            {/* Category description and select/clear all button */}
            <div className="mb-5 flex justify-between items-center">
              <p className="body-sm-regular text-theme-secondary w-full">
                {categories.find(c => c.id === activeCategoryTab)?.description}
              </p>
            </div>

            {/* Search input */}
            {activeCategoryTab !== "conda" && activeCategoryTab !== "extras" && (
              <div className="flex items-center gap-2">
                <div className="flex-1 relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-2 text-theme-muted">
                    <CustomIcon id="search" className="h-4 w-4" />
                  </span>
                  <input
                    id="extension-search"
                    type="text"
                    placeholder="Search extensions..."
                    value={localSearchQuery}
                    onChange={(e) => setLocalSearchQuery(e.target.value)}
                    className="!pl-[30px] w-full text-xs p-2 bg-theme-secondary rounded overflow-hidden text-ellipsis whitespace-nowrap"
                    disabled={loading}
                    spellCheck="false"
                  />
                </div>
              </div>
            )}

            {/* Only show the active tab's category content */}
            <div className="mb-3">
              {categories.map((category) => {
                if (category.id !== activeCategoryTab) return null;

                const categoryExtensions = getFilteredExtensions(category.id);

                return (
                  <div key={category.id}>
                    <div className="flex items-center justify-between">
                      <div className="flex-1" />
                    </div>

                    <div>
                      {/* Select all row for applicable categories */}
                      {(category.id === "provider" || category.id === "router" || category.id === "other-openbb") && (
                        <div className="mt-2 divide-y">
                          <Tooltip
                            content="Deselect all extensions in this category"
                            className="tooltip tooltip-theme"
                          >
                            <input
                              type="checkbox"
                              checked={(getCheckboxState(activeCategoryTab) === 'checked')}
                              onChange={() => {
                                if (
                                  countSelectedInCategory(activeCategoryTab) > 0
                                ) {
                                  clearCategory(activeCategoryTab);
                                } else {
                                  selectCategory(activeCategoryTab);
                                }
                              }}
                              className={`checkbox ${getCheckboxState(activeCategoryTab) === 'indeterminate' ? 'indeterminate' : ''}`}
                            />
                          </Tooltip>
                          {/* Select All Button */}
                          <Tooltip
                            content="Select all extensions in this category."
                            className="tooltip tooltip-theme"
                          >
                            <Button
                              variant="ghost"
                              onClick={() => selectCategory(activeCategoryTab)}
                              className="button-ghost ml-0 body-sm-medium relative -top-0.5"
                              size="xs"
                            >
                              Select All
                            </Button>
                          </Tooltip>
                        </div>
                      )}
                      {/* Conda packages input */}
                      {category.id === "conda" && (
                      <div className="space-y-4 p-1">
                        <div className="flex items-end gap-4">
                        <div className="flex-1">
                          <label htmlFor="conda-channel" className="body-sm-bold text-theme-secondary mb-1 block">
                          Channel
                          </label>
                          <input
                          id="conda-channel"
                          type="text"
                          placeholder="conda-forge"
                          className="form-input text-sm border-theme-accent rounded p-1 w-full body-sm-regular text-theme-primary shadow-md"
                          value={condaChannel}
                          spellCheck="false"
                          onChange={(e) => setCondaChannel(e.target.value)}
                          />
                        </div>
                        <div className="flex-1">
                          <label htmlFor="conda-package" className="body-sm-bold text-theme-secondary mb-1 block">
                          Package
                          </label>
                          <input
                          id="conda-package"
                          type="text"
                          placeholder="Conda Package Name"
                          className="form-input text-sm border-theme-accent rounded p-1 w-full body-sm-regular text-theme-primary shadow-md"
                          value={condaPackage}
                          onChange={(e) => setCondaPackage(e.target.value)}
                          spellCheck="false"
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && condaPackage.trim()) {
                            e.preventDefault();
                            addCondaPackage();
                            }
                          }}
                          />
                        </div>
                        <Button
                          type="button"
                          onClick={addCondaPackage}
                          disabled={!condaPackage.trim()}
                          variant="primary"
                          size="sm"
                          className="button-primary"
                        >
                          Add
                        </Button>
                        </div>
                        {condaPackages.length === 0 && (
                          <div className="w-full min-h-[65px] bg-theme-quartary flex items-center justify-center rounded-sm shadow-sm border border-theme-modal">
                            <div className="body-sm-regular text-theme-muted">No Conda packages added.</div>
                          </div>
                        )}
                        {condaPackages.length > 0 && (
                        <div className="pt-4">
                          <div className="flex flex-col space-y-2 max-h-64 overflow-y-auto pr-1">
                          {condaPackages.map((pkg) => (
                            <div
                            key={pkg}
                            className="flex items-center justify-between bg-theme-quartary rounded-sm px-3 py-3"
                            >
                            <span className="body-sm-regular text-theme-primary">{pkg}</span>
                            <Tooltip content={`Remove ${pkg}`} className="tooltip tooltip-theme">
                              <Button
                                type="button"
                                variant="ghost"
                                onClick={() => removeCondaPackage(pkg)}
                                className="button-ghost h-5 w-5 p-0"
                                aria-label={`Remove ${pkg}`}
                              >
                                <CustomIcon id="close" className="h-4 w-4 text-theme" />
                              </Button>
                            </Tooltip>
                            </div>
                          ))}
                          </div>
                        </div>
                        )}
                      </div>
                      )}
                      {/* Custom package input for extras category */}
                      {category.id === "extras" && (
                      <div className="space-y-4 p-1">
                        <div className="flex items-end gap-4">
                          <div className="flex-1">
                            <label htmlFor="custom-package" className="body-sm-bold text-theme-secondary mb-1 block">
                              Package
                            </label>
                            <input
                              id="custom-package"
                              type="text"
                              placeholder="PyPI Package Name"
                              className="form-input text-sm border-theme-accent rounded p-1 w-full body-sm-regular text-theme-primary shadow-md"
                              value={customPackage}
                              onChange={(e) => setCustomPackage(e.target.value)}
                              spellCheck="false"
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && customPackage.trim()) {
                                  e.preventDefault();
                                  addCustomPackage();
                                }
                              }}
                            />
                          </div>
                          <Button
                            type="button"
                            onClick={addCustomPackage}
                            disabled={!customPackage.trim()}
                            variant="primary"
                            size="sm"
                            className="button-primary"
                          >
                            Add
                          </Button>
                        </div>
                        {customPackages.length === 0 && (
                        <div className="w-full min-h-[65px] bg-theme-quartary flex items-center justify-center rounded-sm shadow-sm border border-theme-modal">
                        <div className="body-sm-regular text-theme-muted">No PyPI packages added.</div>
                        </div>
                        )}
                        {customPackages.length > 0 && (
                          <div className="pt-4">
                            <div className="flex flex-col space-y-2 max-h-64 overflow-y-auto pr-1">
                              {customPackages.map((pkg) => (
                                <div
                                  key={pkg}
                                  className="flex items-center justify-between bg-theme-quartary rounded-sm p-3"
                                >
                                  <span className="body-sm-regular text-theme-primary">{pkg}</span>
                                  <Tooltip content={`Remove ${pkg}`} className="tooltip tooltip-theme">
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      onClick={() => removeCustomPackage(pkg)}
                                      className="button-ghost h-5 w-5 p-0"
                                      aria-label={`Remove ${pkg}`}
                                    >
                                      <CustomIcon id="close" className="h-4 w-4 text-theme" />
                                    </Button>
                                  </Tooltip>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                      )}
                      {categoryExtensions.length === 0 ? (
                      category.id !== "conda" && category.id !== "extras" && (
                        <div className="p-3 body-xs-regular text-theme-muted bg-theme-quartary rounded-sm shadow-sm border border-theme-modal w-full min-h-[65px] flex items-center justify-center">
                        {localSearchQuery.trim()
                          ? "No extensions in this category match the search."
                          : "No extensions available in this category. If they are already installed, they will not appear here."}
                        </div>
                      )
                      ) : (
                      <div>
                        <div className="overflow-y-auto">
                          <div className="flex flex-col space-y-2 max-h-[calc(100vh-32rem)] min-h-[100px] mr-2">
                          {categoryExtensions.map((extension) => (
                          <div
                            key={extension.id}
                            className="flex items-start justify-between p-2 rounded-sm bg-theme-quartary text-theme-primary relative border border-theme-modal"
                          >
                            <input
                            type="checkbox"
                            id={`ext-${extension.id}`}
                            checked={selectedExtensions.includes(
                              extension.id,
                            )}
                            onChange={() => toggleExtension(extension.id)}
                            className="checkbox mt-1 h-4 w-4 text-theme-accent"
                            />
                            <div className="ml-3 w-full">
                            <div className="flex flex-wrap items-center justify-start gap-4 w-full">
                              <label
                              htmlFor={`ext-${extension.id}`}
                              className="text-theme-primary body-md-regular cursor-pointer"
                              >
                              {extension.id}
                              </label>
                              {extension.credentials &&
                              extension.credentials.length > 0 && (
                                <div className="relative inline-block group">
                                <span
                                  className="px-2 py-0.5 bg-theme-accent text-theme-accent body-xs-medium rounded-full"
                                  title="API key required"
                                >
                                  {extension.credentials.join(", ")}
                                </span>
                                </div>
                              )}
                            </div>
                            <p className="text-theme-secondary body-sm-regular mt-2">
                              {extension.description}
                            </p>
                            {extension.instructions && (
                              <div className="bg-theme-primary p-2 mt-2 body-xs-regular text-theme-secondary rounded-sm shadow-sm">
                                <details>
                                  <summary className="cursor-pointer text-theme-primary body-xs-medium">
                                  Setup instructions
                                  </summary>
                                  <div className="mt-2 p-2">
                                    <ReactMarkdown
                                      className="markdown-content whitespace-pre-line"
                                      components={{
                                        img: ({ ...props }) => (
                                          <img
                                            {...props}
                                            className="max-w-full h-auto border border-theme rounded-md"
                                            style={{
                                              maxHeight: "300px",
                                            }}
                                            loading="lazy"
                                            alt={
                                              props.alt ||
                                              "Setup instruction image"
                                            }
                                          />
                                        ),
                                        a: ({ ...props }) => (
                                          <a
                                            {...props}
                                            className="text-blue-500 underline"
                                            target="_blank"
                                            rel="noreferrer noopener"
                                          />
                                        ),
                                        p: ({ ...props }) => (
                                          <p
                                            {...props}
                                            className="my-2 text-theme-secondary"
                                          />
                                        ),
                                        code: ({ ...props }) => (
                                          <code
                                            {...props}
                                            className="bg-theme-tertiary px-1 py-0.5 rounded text-theme-primary"
                                          />
                                        ),
                                        div: ({ ...props }) => (
                                          <div {...props} />
                                        ),
                                      }}
                                    >
                                      {extension.instructions}
                                    </ReactMarkdown>
                                  </div>
                                </details>
                              </div>
                            )}
                            </div>
                          </div>
                          ))}
                        </div>
                        </div>
                      </div>
                      )}
                    </div>
                    </div>
                  );
                  })}
                </div>

            {/* Global Summary and Install button */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 ml-5">
                <span className="text-xs text-theme-muted flex items-center">
                  {condaPackages.length} Conda + {customPackages.length} PyPI + {selectedExtensions.length} OpenBB extensions selected
                </span>
              </div>
              <div className="flex items-center gap-4">
                <Tooltip
                  content="Cancel and go back."
                  className="tooltip-theme"
                >
                  <Button
                    onClick={onCancel}
                    variant="outline"
                    size="sm"
                    className="button-outline shadow-md"
                    disabled={isInstalling}
                  >
                    Cancel
                  </Button>
                </Tooltip>
                <Tooltip
                  content="Install the selected extensions."
                  className="tooltip-theme"
                >
                  <Button
                    onClick={handleInstallExtensions}
                    variant="primary"
                    size="sm"
                    className="button-primary shadow-md"
                    disabled={
                      isInstalling ||
                      (
                        selectedExtensions.length === 0 &&
                        customPackages.length === 0 &&
                        condaPackages.length === 0
                      )
                    }
                  >
                    {isInstalling ? "Installing..." : "Install"}
                  </Button>
                </Tooltip>
              </div>
            </div>
          </>
        )}
        {error && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="bg-theme-secondary border-red-800 rounded-lg shadow-lg max-w-2xl w-full p-6">
            <h2 className="text-red-600 text-lg font-bold mb-2">Extension Error</h2>
            <div className="mb-4 mt-4 pl-5 pt-1 pr-1 pb-1 border-red-800 bg-red-900/30 text-red-300 rounded-md text-xs font-mono">
              <div className="whitespace-pre-wrap overflow-auto max-h-60 mt-0.5 mb-0.5">
                {error}
              </div>
            </div>
            <div className="flex justify-end">
              <Button
              onClick={() => setError(null)}
              variant="outline"
              size="sm"
              className="button-outline shadow-sm"
              >
              <span className="body-xs-bold text-theme">Dismiss</span>
              </Button>
            </div>
          </div>
        </div>
        )}
      </div>
    </div>
  );
};
