App({
  onLaunch() {
    wx.cloud.init({
      env: "cloud1-6gov01mkc0cce40b",
      traceUser: true,
    });
  },
});
