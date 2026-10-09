const navLinks = document.querySelectorAll(".nav > a[href]");
const navDropdowns = document.querySelectorAll(".nav-dropdown");
const placeholderLinks = document.querySelectorAll("a[href='#']");
const gatedAssets = document.querySelectorAll("[data-gated-asset]");
const countUpValues = document.querySelectorAll("[data-count-up]");
const lightbox = document.querySelector("[data-image-lightbox]");
const lightboxImage = document.querySelector("[data-lightbox-image]");
const lightboxClose = document.querySelector("[data-lightbox-close]");
const lightboxTriggers = document.querySelectorAll(".assembly-wiki-step img, [data-lightbox-trigger]");
const youtubeVideos = document.querySelectorAll("[data-youtube-video]");
const licenseModal = document.querySelector("[data-license-modal]");
const licenseForm = document.querySelector("[data-license-form]");
const licenseCancel = document.querySelector("[data-license-cancel]");
const licenseAssetLabel = document.querySelector("[data-license-asset]");
const licenseStatus = document.querySelector("[data-license-status]");

const currentPage = window.location.pathname.split("/").pop() || "index.html";
const licenseProfileKey = "midas-cad-license-profile";
let pendingAsset = null;
let lastAssetTrigger = null;

const normalizePage = (href) => {
  const url = new URL(href, window.location.href);
  return url.pathname.split("/").pop() || "index.html";
};

navLinks.forEach((link) => {
  link.classList.toggle("active", normalizePage(link.href) === currentPage);
});

navDropdowns.forEach((dropdown) => {
  const dropdownLinks = dropdown.querySelectorAll("a[href]");
  const isActive = Array.from(dropdownLinks).some((link) => normalizePage(link.href) === currentPage);
  dropdown.classList.toggle("active", isActive);
});

placeholderLinks.forEach((link) => {
  link.setAttribute("aria-disabled", "true");
  link.addEventListener("click", (event) => {
    event.preventDefault();
  });
});

const formatCountValue = (value, element) => {
  const decimals = Number(element.dataset.countDecimals || 0);
  const prefix = element.dataset.countPrefix || "";
  const suffix = element.dataset.countSuffix || "";
  const formattedNumber = element.dataset.countFormat === "currency"
    ? value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })
    : value.toFixed(decimals);

  return `${prefix}${formattedNumber}${suffix}`;
};

const animateCountValue = (element) => {
  if (element.dataset.countAnimated === "true") {
    return;
  }

  element.dataset.countAnimated = "true";

  const target = Number(element.dataset.countTarget);
  if (!Number.isFinite(target)) {
    return;
  }

  const duration = 2000;
  const startTime = performance.now();

  const tick = (now) => {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    element.textContent = formatCountValue(target * eased, element);

    if (progress < 1) {
      requestAnimationFrame(tick);
      return;
    }

    element.textContent = formatCountValue(target, element);
  };

  requestAnimationFrame(tick);
};

if (
  countUpValues.length
  && "IntersectionObserver" in window
  && !window.matchMedia("(prefers-reduced-motion: reduce)").matches
) {
  const countObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) {
        return;
      }

      animateCountValue(entry.target);
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.35 });

  countUpValues.forEach((element) => countObserver.observe(element));
}

const closeLightbox = () => {
  if (!lightbox || !lightboxImage) {
    return;
  }

  lightbox.hidden = true;
  document.body.classList.remove("modal-open");
  lightboxImage.src = "";
  lightboxImage.alt = "";
};

const imageFromLightboxTrigger = (trigger) => (
  trigger.matches("img") ? trigger : trigger.querySelector("img")
);

const openLightbox = (image) => {
  if (!image) {
    return;
  }

  if (!lightbox || !lightboxImage) {
    return;
  }

  lightboxImage.src = image.currentSrc || image.src;
  lightboxImage.alt = image.alt || "Enlarged image";
  lightbox.hidden = false;
  document.body.classList.add("modal-open");
  lightboxClose?.focus();
};

lightboxTriggers.forEach((trigger) => {
  const image = imageFromLightboxTrigger(trigger);
  image?.closest("figure")?.classList.add("is-zoomable");

  trigger.addEventListener("click", () => {
    if (!lightbox || !lightboxImage) {
      return;
    }

    openLightbox(image);
  });
});

lightboxClose?.addEventListener("click", closeLightbox);

lightbox?.addEventListener("click", (event) => {
  if (event.target === lightbox) {
    closeLightbox();
  }
});

const loadYoutubeVideo = (poster, { muted = false } = {}) => {
  const videoUrl = poster.dataset.youtubeSrc;
  if (!videoUrl) {
    return;
  }

  const iframe = document.createElement("iframe");
  const params = new URLSearchParams({ autoplay: "1" });
  const shouldLoop = poster.closest(".demo-card") || poster.dataset.youtubeLoop === "true";
  if (muted) {
    params.set("mute", "1");
    params.set("playsinline", "1");
  }
  if (shouldLoop) {
    const videoId = videoUrl.match(/\/embed\/([^?]+)/)?.[1];
    params.set("loop", "1");
    if (videoId) {
      params.set("playlist", videoId);
    }
  }

  const separator = videoUrl.includes("?") ? "&" : "?";
  iframe.title = poster.dataset.youtubeTitle || "Video walkthrough";
  iframe.src = `${videoUrl}${separator}${params.toString()}`;
  iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
  iframe.allowFullscreen = true;

  poster.replaceWith(iframe);
};

youtubeVideos.forEach((poster) => {
  if (poster.dataset.youtubeAutoplay === "true") {
    loadYoutubeVideo(poster, { muted: true });
    return;
  }

  poster.addEventListener("click", () => {
    const videoUrl = poster.dataset.youtubeSrc;
    if (!videoUrl) {
      return;
    }

    loadYoutubeVideo(poster);
  });
});

const openAsset = (asset) => {
  if (!asset?.url) {
    return;
  }

  if (asset.action === "open") {
    window.open(asset.url, "_blank", "noopener,noreferrer");
    return;
  }

  const link = document.createElement("a");
  link.href = asset.url;
  if (asset.filename) {
    link.download = asset.filename;
  }
  document.body.append(link);
  link.click();
  link.remove();
};

const assetFromButton = (button) => ({
  title: button.dataset.assetTitle,
  url: button.dataset.assetUrl,
  filename: button.dataset.assetFilename,
  action: button.dataset.assetAction,
});

const getStoredLicenseProfile = () => {
  try {
    return JSON.parse(sessionStorage.getItem(licenseProfileKey) || "null");
  } catch {
    sessionStorage.removeItem(licenseProfileKey);
    return null;
  }
};

const storeLicenseProfile = (profile) => {
  sessionStorage.setItem(licenseProfileKey, JSON.stringify(profile));
};

const closeLicenseModal = () => {
  if (!licenseModal) {
    return;
  }

  licenseModal.hidden = true;
  document.body.classList.remove("modal-open");
  if (licenseStatus) {
    licenseStatus.hidden = true;
    licenseStatus.textContent = "";
  }
  lastAssetTrigger?.focus();
};

const showLicenseModal = (button) => {
  if (!licenseModal || !licenseForm) {
    openAsset(assetFromButton(button));
    return;
  }

  pendingAsset = assetFromButton(button);
  lastAssetTrigger = button;

  if (licenseAssetLabel) {
    licenseAssetLabel.textContent = pendingAsset.title || "Selected CAD asset";
  }

  licenseModal.hidden = false;
  document.body.classList.add("modal-open");
  licenseForm.querySelector("input")?.focus();
};

const setLicenseSubmitting = (isSubmitting) => {
  const submitButton = licenseForm?.querySelector("button[type='submit']");
  if (!submitButton) {
    return;
  }

  submitButton.disabled = isSubmitting;
  submitButton.textContent = isSubmitting ? "Submitting..." : "Continue";
};

const profileFromLicenseForm = () => {
  const formData = new FormData(licenseForm);

  return {
    name: formData.get("name") || "",
    email: formData.get("email") || "",
    organization: formData.get("organization") || "",
  };
};

const submitLicenseResponse = async (profile, asset) => {
  const formAction = licenseForm?.dataset.googleFormAction;
  if (!formAction || !licenseForm) {
    return;
  }

  const googleFormData = new FormData();
  googleFormData.append(licenseForm.dataset.entryName, profile.name || "");
  googleFormData.append(licenseForm.dataset.entryEmail, profile.email || "");
  googleFormData.append(licenseForm.dataset.entryOrganization, profile.organization || "");
  googleFormData.append(licenseForm.dataset.entryAsset, asset?.title || "Selected CAD asset");

  await fetch(formAction, {
    method: "POST",
    mode: "no-cors",
    body: googleFormData,
  });
};

const submitStoredLicenseAndOpen = async (button) => {
  const profile = getStoredLicenseProfile();
  const asset = assetFromButton(button);

  if (!profile) {
    showLicenseModal(button);
    return;
  }

  let openedWindow = null;
  if (asset.action === "open") {
    openedWindow = window.open("about:blank", "_blank");
    if (openedWindow) {
      openedWindow.opener = null;
    }
  }

  button.disabled = true;

  try {
    await submitLicenseResponse(profile, asset);
    if (openedWindow) {
      openedWindow.location.href = asset.url;
      return;
    }
    openAsset(asset);
  } catch {
    if (openedWindow) {
      openedWindow.close();
    }
    showLicenseModal(button);
    if (licenseStatus) {
      licenseStatus.hidden = false;
      licenseStatus.textContent = "Could not submit the saved access response. Please check your connection and try again.";
    }
  } finally {
    button.disabled = false;
  }
};

gatedAssets.forEach((button) => {
  button.addEventListener("click", () => {
    submitStoredLicenseAndOpen(button);
  });
});

licenseForm?.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!licenseForm.reportValidity()) {
    return;
  }

  if (licenseStatus) {
    licenseStatus.hidden = false;
    licenseStatus.textContent = "Submitting access response...";
  }

  setLicenseSubmitting(true);
  let openedWindow = null;

  try {
    const profile = profileFromLicenseForm();
    if (pendingAsset?.action === "open") {
      openedWindow = window.open("about:blank", "_blank");
      if (openedWindow) {
        openedWindow.opener = null;
      }
    }

    await submitLicenseResponse(profile, pendingAsset);
    storeLicenseProfile(profile);
    const asset = pendingAsset;
    pendingAsset = null;
    closeLicenseModal();
    if (openedWindow) {
      openedWindow.location.href = asset.url;
      return;
    }
    openAsset(asset);
  } catch {
    if (openedWindow) {
      openedWindow.close();
    }
    if (licenseStatus) {
      licenseStatus.hidden = false;
      licenseStatus.textContent = "Could not submit the access response. Please check your connection and try again.";
    }
  } finally {
    setLicenseSubmitting(false);
  }
});

licenseCancel?.addEventListener("click", () => {
  pendingAsset = null;
  closeLicenseModal();
});

licenseModal?.addEventListener("click", (event) => {
  if (event.target === licenseModal) {
    pendingAsset = null;
    closeLicenseModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && lightbox && !lightbox.hidden) {
    closeLightbox();
    return;
  }

  if (event.key === "Escape" && licenseModal && !licenseModal.hidden) {
    pendingAsset = null;
    closeLicenseModal();
  }
});
