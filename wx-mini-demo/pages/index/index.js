const CLOUD_ENV_ID = "cloud1-6gov01mkc0cce40b";
const CLOUD_SERVICE = "cloud1";

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch (_e) {
    return text;
  }
}

function unwrapContainerResponse(res) {
  if (!res) return null;

  // Common shape: { statusCode, data, header, errMsg }
  let payload = res.data;
  if (typeof payload === "string") {
    payload = safeJsonParse(payload);
  }

  // Some gateways wrap business payload again in `data`
  if (payload && typeof payload === "object" && payload.data !== undefined) {
    const nested = payload.data;
    if (typeof nested === "string") {
      return safeJsonParse(nested);
    }
    return nested;
  }
  return payload;
}

function callContainer({ path, method = "GET", data = null }) {
  return new Promise((resolve, reject) => {
    wx.cloud.callContainer({
      config: {
        env: CLOUD_ENV_ID,
      },
      path,
      method,
      header: {
        "X-WX-SERVICE": CLOUD_SERVICE,
        "content-type": "application/json",
      },
      data,
      success: (res) => {
        const business = unwrapContainerResponse(res);
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(business)}`));
          return;
        }
        resolve(business);
      },
      fail: reject,
    });
  });
}

Page({
  data: {
    loading: false,
    statusText: "初始化中...",
    locationText: "定位中...",
    city: "",
    country: "",
    latitude: null,
    longitude: null,
    distance: 10000,
    themeDetails: [],
    themeLabels: [],
    themeIndex: 0,
    selectedTheme: "terracotta",
    themeDescription: "",
    themePreview: {
      bg: "#ffffff",
      text: "#111111",
      water: "#9ec5fe",
      parks: "#9fd7a6",
      road_primary: "#5f6b7a",
      road_secondary: "#8a95a3",
    },
    posterPath: "",
    posterBase64: "",
  },

  async onLoad() {
    await this.loadThemes();
    await this.locateUser();
  },

  async loadThemes() {
    try {
      const payload = await callContainer({ path: "/api/themes/details", method: "GET" });
      const themes = Array.isArray(payload.themes) ? payload.themes : [];
      if (!themes.length) {
        throw new Error("No themes returned");
      }

      const labels = themes.map((item) => `${item.name} (${item.id})`);
      const defaultIndex = Math.max(themes.findIndex((item) => item.id === "terracotta"), 0);
      const selected = themes[defaultIndex];

      this.setData({
        themeDetails: themes,
        themeLabels: labels,
        themeIndex: defaultIndex,
        selectedTheme: selected.id,
        themeDescription: selected.description || "",
        themePreview: {
          bg: selected.bg,
          text: selected.text,
          water: selected.water,
          parks: selected.parks,
          road_primary: selected.road_primary,
          road_secondary: selected.road_secondary,
        },
      });
    } catch (error) {
      this.setData({
        statusText: `主题加载失败：${error.errMsg || error.message || JSON.stringify(error)}`,
      });
    }
  },

  onThemeChange(e) {
    const idx = Number(e.detail.value || 0);
    const selected = this.data.themeDetails[idx];
    if (!selected) return;
    this.setData({
      themeIndex: idx,
      selectedTheme: selected.id,
      themeDescription: selected.description || "",
      themePreview: {
        bg: selected.bg,
        text: selected.text,
        water: selected.water,
        parks: selected.parks,
        road_primary: selected.road_primary,
        road_secondary: selected.road_secondary,
      },
    });
  },

  onDistanceChanging(e) {
    this.setData({ distance: Math.round(e.detail.value) });
  },

  onDistanceChange(e) {
    this.setData({ distance: Math.round(e.detail.value) });
  },

  onRelocate() {
    this.locateUser();
  },

  locateUser() {
    this.setData({
      statusText: "正在获取定位...",
      locationText: "定位中...",
    });

    return new Promise((resolve) => {
      wx.getLocation({
        type: "gcj02",
        success: async (loc) => {
          const lat = loc.latitude;
          const lon = loc.longitude;

          try {
            const reverse = await callContainer({
              path: `/api/location/reverse?latitude=${encodeURIComponent(lat)}&longitude=${encodeURIComponent(lon)}`,
              method: "GET",
            });
            const city = reverse.city || "Current Location";
            const country = reverse.country || "Unknown";
            this.setData({
              city,
              country,
              latitude: lat,
              longitude: lon,
              locationText: `${city}, ${country}`,
              statusText: "定位成功，可直接生成。",
            });
          } catch (_error) {
            this.setData({
              city: "Current Location",
              country: "Unknown",
              latitude: lat,
              longitude: lon,
              locationText: `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
              statusText: "定位成功（城市解析失败，已使用坐标）。",
            });
          }
          resolve();
        },
        fail: (err) => {
          this.setData({
            locationText: "未授权",
            statusText: `定位失败：${err.errMsg || "请授权定位权限"}`,
          });
          resolve();
        },
      });
    });
  },

  async onGenerate() {
    const { city, country, latitude, longitude, selectedTheme, distance } = this.data;
    if (latitude === null || longitude === null) {
      wx.showToast({ title: "请先授权定位", icon: "none" });
      return;
    }

    this.setData({
      loading: true,
      statusText: "生成中，请稍候...",
      posterPath: "",
      posterBase64: "",
    });

    try {
      const result = await callContainer({
        path: "/api/posters/generate-base64",
        method: "POST",
        data: {
          city,
          country,
          theme: selectedTheme,
          distance,
          width: 4,
          height: 6,
          latitude: String(latitude),
          longitude: String(longitude),
          display_city: city,
          display_country: country,
        },
      });

      if (!result || !result.image_base64) {
        throw new Error(`No image returned: ${JSON.stringify(result)}`);
      }

      const posterPath = `data:${result.mime_type || "image/png"};base64,${result.image_base64}`;
      this.setData({
        posterPath,
        posterBase64: result.image_base64,
        statusText: `生成成功：${city}`,
      });
    } catch (error) {
      this.setData({
        statusText: `生成失败：${error.errMsg || error.message || JSON.stringify(error)}`,
      });
    } finally {
      this.setData({ loading: false });
    }
  },

  onSave() {
    const { posterBase64 } = this.data;
    if (!posterBase64) return;

    const fs = wx.getFileSystemManager();
    const filePath = `${wx.env.USER_DATA_PATH}/poster_${Date.now()}.png`;
    fs.writeFile({
      filePath,
      data: wx.base64ToArrayBuffer(posterBase64),
      encoding: "binary",
      success: () => {
        wx.saveImageToPhotosAlbum({
          filePath,
          success: () => wx.showToast({ title: "已保存" }),
          fail: () => wx.showToast({ title: "保存失败，请检查权限", icon: "none" }),
        });
      },
      fail: () => {
        wx.showToast({ title: "图片写入失败", icon: "none" });
      },
    });
  },
});
