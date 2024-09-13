const path = require('path');

module.exports = {
  entry: './static/images/js/worker.js',
  output: {
    filename: 'worker.bundle.js',
    path: path.resolve(__dirname, 'static/images/js'),
  },
  mode: 'production',
  target: 'webworker',
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
          options: {
            presets: ['@babel/preset-env'],
          },
        },
      },
    ],
  },
  resolve: {
    extensions: ['.js'],
  },
};