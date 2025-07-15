import os
import MySQLdb
import smtplib
import random
import string
from datetime import datetime
from flask import Flask, session, url_for, redirect, render_template, request, abort, flash, send_file, Response, jsonify
from database import db_connect, vcact2, upload, ins_loginact, inc_reg
import base64
import io
import json
import re
import tensorflow as tf
from collections import namedtuple
from collections import defaultdict
from io import StringIO
from PIL import Image
import numpy as np
import winsound
from geopy.geocoders import Nominatim
import cv2

global filename
global detectionGraph
global msg

app = Flask(__name__)
app.secret_key = os.urandom(24)

def get_location_name(latitude, longitude):
    geolocator = Nominatim(user_agent="location_lookup")
    location = geolocator.reverse((latitude, longitude), language='en')
    return location.address if location else "Unknown Location"

@app.route("/")
def FUN_root():
    return render_template("index.html")

@app.route("/inceregact", methods=['GET', 'POST'])
def inceregact():
    if request.method == 'POST':
        status = inc_reg(request.form['username'], request.form['password'], request.form['email'], request.form['mobile'], request.form['address'])
        if status == 1:
            return render_template("log.html", m1="success")
        else:
            return render_template("register.html", m1="failed")

@app.route("/inslogin", methods=['GET', 'POST'])
def inslogin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        status = ins_loginact(username, password)
        if status == 1:
            c, conn = db_connect()
            c.execute("SELECT username, email, mobile, address FROM user WHERE username = %s", (username,))
            user_data = c.fetchone()
            conn.close()
            if user_data:
                session['username'] = user_data[0]
                session['email'] = user_data[1]
                session['mobile'] = user_data[2]
                session['address'] = user_data[3]
            else:
                return render_template("log.html", m1="User not found")
            return render_template("uhome.html", m1="success")
        else:
            return render_template("log.html", m1="Login Failed")
    return render_template("log.html")

@app.route("/admin.html")
def admin():
    return render_template("admin.html")

@app.route("/index.html")
def index():
    return render_template("index.html")

@app.route("/log.html")
def login():
    return render_template("log.html")

@app.route("/register.html")
def reg():
    return render_template("register.html")

@app.route("/uhome.html")
def uhome():
    return render_template("uhome.html")

@app.route("/vc.html")
def vc():
    data1 = vcact2()
    return render_template("vc.html", data1=data1)

def generate_random_string(length):
    letters = string.ascii_letters
    return ''.join(random.choice(letters) for _ in range(length))

def rectArea(xmax, ymax, xmin, ymin):
    x = np.abs(xmax - xmin)
    y = np.abs(ymax - ymin)
    return x * y

def extract_street_name(location_name):
    match = re.search(r'\b(\d+-\d+,?\s)?([\w\s]+),', location_name)
    if match:
        return match.group(2)
    else:
        return None

def area(a, b):
    dx = min(a.xmax, b.xmax) - max(a.xmin, b.xmin)
    dy = min(a.ymax, b.ymax) - max(a.ymin, b.ymin)
    return dx * dy

def calculateCollision(boxes, classes, scores, image_np):
    global msg
    for i, b in enumerate(boxes[0]):
        if classes[0][i] == 3 or classes[0][i] == 6 or classes[0][i] == 8:
            if scores[0][i] > 0.5:
                for j, c in enumerate(boxes[0]):
                    if (i != j) and (classes[0][j] == 3 or classes[0][j] == 6 or classes[0][j] == 8) and scores[0][j] > 0.5:
                        Rectangle = namedtuple('Rectangle', 'xmin ymin xmax ymax')
                        ra = Rectangle(boxes[0][i][3], boxes[0][i][2], boxes[0][i][1], boxes[0][i][3])
                        rb = Rectangle(boxes[0][j][3], boxes[0][j][2], boxes[0][j][1], boxes[0][j][3])
                        ar = rectArea(boxes[0][i][3], boxes[0][i][1], boxes[0][i][2], boxes[0][i][3])
                        col_threshold = 0.6 * np.sqrt(ar)
                        if area(ra, rb) and area(ra, rb) < col_threshold:
                            msg = 'ACCIDENT'
                            beep()
                            return True
    return False

@app.route("/showact", methods=['GET', 'POST'])
def showact():
    c1 = request.args.get('c')
    d1 = request.args.get('d')
    return render_template("show.html", c1=c1, d1=d1)

def beep():
    frequency = 2500
    duration = 1000
    winsound.Beep(frequency, duration)

@app.route('/detect')
def detect():
    global msg
    msg = ''
    detectionGraph = tf.Graph()
    with detectionGraph.as_default():
        od_graphDef = tf.GraphDef()
        with tf.gfile.GFile('model/accident_detection.pb', 'rb') as file:
            serializedGraph = file.read()
            od_graphDef.ParseFromString(serializedGraph)
            tf.import_graph_def(od_graphDef, name='')

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return render_template("admin.html", error="Failed to open camera")

    with detectionGraph.as_default():
        with tf.Session(graph=detectionGraph) as sess:
            accident_detected = False
            last_accident_time = 0
            cooldown_period = 5  # seconds to wait before detecting another accident

            while True:
                ret, image_np = cap.read()
                if not ret:
                    break

                current_time = datetime.now().timestamp()

                # Only process detection if not in cooldown period
                if not accident_detected or (current_time - last_accident_time) > cooldown_period:
                    image_np_expanded = np.expand_dims(image_np, axis=0)
                    image_tensor = detectionGraph.get_tensor_by_name('image_tensor:0')
                    boxes = detectionGraph.get_tensor_by_name('detection_boxes:0')
                    scores = detectionGraph.get_tensor_by_name('detection_scores:0')
                    classes = detectionGraph.get_tensor_by_name('detection_classes:0')
                    num_detections = detectionGraph.get_tensor_by_name('num_detections:0')
                    (boxes, scores, classes, num_detections) = sess.run(
                        [boxes, scores, classes, num_detections], feed_dict={image_tensor: image_np_expanded})

                    if calculateCollision(boxes, classes, scores, image_np):
                        accident_detected = True
                        last_accident_time = current_time
                        random_string = generate_random_string(4)
                        image_path = f"static/uploads/{random_string}.jpg"
                        cv2.imwrite(image_path, image_np)
                        
                        from urllib.request import urlopen
                        url = 'http://ipinfo.io/json'
                        response = urlopen(url)
                        location = json.load(response)
                        latitude, longitude = map(float, location['loc'].split(','))
                        location_name = get_location_name(latitude, longitude)
                        street_name = "ACE Engineering College ENGINEERING BLOCK ACE ENGINEERING COLLEGE Ankushapur Ghatkesar Telangana"
                        
                        c, conn = db_connect()
                        c.execute("SELECT address FROM user WHERE username = %s", (session['username'],))
                        row = c.fetchone()
                        address = row[0] if row else "Unknown Address"
                        upload(image_path, address, street_name)
                        conn.close()

                cv2.putText(image_np, msg, (230, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 0), 2, cv2.LINE_AA)
                cv2.imshow('Accident Detection', image_np)

                key = cv2.waitKey(25) & 0xFF
                if key == ord('q'):
                    break
                
                # Reset detection state after cooldown
                if accident_detected and (current_time - last_accident_time) > cooldown_period:
                    accident_detected = False
                    msg = ''

            # Cleanup
            cap.release()
            cv2.destroyAllWindows()

    return render_template("admin.html")

if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=5000)
