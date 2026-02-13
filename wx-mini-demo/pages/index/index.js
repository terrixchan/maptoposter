const CLOUD_ENV_ID = 'cloud1-6gov01mkc0cce40b';
const CLOUD_SERVICE = 'cloud1';

Page({
  data: {
    city: 'Tokyo',
    country: 'Japan',
    theme: 'terracotta',
    loading: false,
    posterPath: '',
    posterBase64: ''
  },

  onCityInput(e) {
    this.setData({ city: e.detail.value });
  },

  onCountryInput(e) {
    this.setData({ country: e.detail.value });
  },

  onThemeInput(e) {
    this.setData({ theme: e.detail.value });
  },

  onGenerate() {
    const { city, country, theme } = this.data;
    if (!city || !country) {
      wx.showToast({ title: '请输入城市和国家', icon: 'none' });
      return;
    }

    this.setData({ loading: true, posterPath: '', posterBase64: '' });
    wx.cloud.callContainer({
      config: {
        env: CLOUD_ENV_ID
      },
      path: '/api/posters/generate-base64',
      method: 'POST',
      header: {
        'X-WX-SERVICE': CLOUD_SERVICE,
        'content-type': 'application/json'
      },
      data: {
        city,
        country,
        theme,
        width: 4,
        height: 6,
        distance: 12000
      },
      success: (res) => {
        const result = res.data || {};
        if (!result.image_base64) {
          wx.showToast({ title: '生成失败', icon: 'none' });
          return;
        }
        const base64Src = `data:${result.mime_type || 'image/png'};base64,${result.image_base64}`;
        this.setData({
          posterPath: base64Src,
          posterBase64: result.image_base64
        });
      },
      fail: (err) => {
        const msg = (err && err.errMsg) ? err.errMsg : '容器调用失败';
        wx.showToast({ title: msg, icon: 'none' });
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
  },

  onSave() {
    const { posterBase64 } = this.data;
    if (!posterBase64) return;

    const fs = wx.getFileSystemManager();
    const filePath = `${wx.env.USER_DATA_PATH}/poster_${Date.now()}.png`;
    fs.writeFile({
      filePath,
      data: wx.base64ToArrayBuffer(posterBase64),
      encoding: 'binary',
      success: () => {
        wx.saveImageToPhotosAlbum({
          filePath,
          success: () => wx.showToast({ title: '已保存' }),
          fail: () => wx.showToast({ title: '保存失败，请检查权限', icon: 'none' })
        });
      },
      fail: () => wx.showToast({ title: '写入图片失败', icon: 'none' })
    });
  }
});
